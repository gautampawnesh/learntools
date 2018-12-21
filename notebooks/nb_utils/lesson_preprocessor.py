import re
import logging
import os
import subprocess

import nbformat
from nbconvert.preprocessors import Preprocessor

from nb_utils.macro_processing import MacroProcessor

DEBUG = 0
if DEBUG:
    logging.basicConfig(level=logging.DEBUG)

IGNORE_UNKNOWN_MACROS = 0

class UnrecognizedMacroException(Exception):
    pass

def get_git_branch():
    """Return the current git branch as a string"""
    return subprocess.check_output(["git", "symbolic-ref", "--short", "HEAD"])\
            .decode('utf8').strip()

class LearnLessonPreprocessor(Preprocessor):

    # NB: This is the only overridden Preprocessor method. All other methods are custom.
    def preprocess(self, nb, resources):
        # See render.py for how resources as populated.
        self.track = resources['track_meta']

        # May be None for notebooks with type='extra'
        self.lesson = resources['lesson']
        # Corresponds to track_config.yaml
        track_cfg = resources['track_cfg']
        self.cfg = track_cfg
        nb_meta = resources['nb_meta']

        macroer = MacroProcessor(track_cfg)

        new_cells = []
        for cell in nb.cells:
            # XXX: Kind of hacky implementation.
            src = cell['source']
            if src.strip() == '#%%RM_BELOW%%':
                break
            c = self.process_cell(cell)
            c = c and macroer.process_cell(c)
            if c is not None:
                new_cells.append(c)

        # Add header and footer for self-passed courses, but not for daily-email notebooks (where it'd be confusing)
        if not self.cfg.get('daily'):
            self.add_header_and_footer(new_cells)

        nb.cells = new_cells
        # NB: There may be some cases where we need to access learntools in a tutorial
        # or ancillary notebook as well. We encode this in track_meta. 
        if track_cfg.get('development', False) and nb_meta.type == 'exercise':
            self.pip_install_lt_hack(nb)
        return nb, resources

    def add_header_and_footer(self, cells):
        """Returns a list of cells with a header cell first, followed by cells (which is a list), followed by a footer cell"""
        course_info ="""**[{} Course Home Page]({})**""".format(self.track.course_name, self.track.course_url)
 
        header_content = course info + "\n---"
        footer_content = "---\n" + course_info
        header_cell = make_cell(cell_type='markdown', source=header_content)
        footer_cell = make_cell(cell_type='markdown', source=footer_content)
        return header_cell + cells + footer_cells

    def pip_install_lt_hack(self, nb):
        """pip install learntools @ the present branch when running on Kernels"""
        try:
            branch = get_git_branch()
        except subprocess.CalledProcessError:
            # This call fails in CI. The reason is unclear, but it's benign enough
            # that we can just ignore it and forge on.
            logging.warn("Failed to capture current git branch. Falling back to master.")
            branch = 'master'
        pkg = 'git+https://github.com/Kaggle/learntools.git@{}'.format(branch)
        self.pip_install_hack(nb, [pkg])

    def pip_install_hack(self, nb, pkgs):
        """Insert some cells at the top of this notebook that pip install the given
        packages to /kaggle/working, then add that directory to sys.path.
        """
        if not pkgs:
            return
        extra_cells = []
        for pkg in pkgs:
            extra_cells.append(self.pip_install_cell(pkg))

        # NB: Workaround for 'read-only file sytem' issue when pip installing.
        # Hopefully at some point this becomes easier.
        syspath_lines = [
                'import sys\n',
                "sys.path.append('/kaggle/working')",
        ]
        syspath_cell = self.make_cell(cell_type='code', source=syspath_lines)
        extra_cells.append(syspath_cell)
        nb.cells = extra_cells + nb.cells

    @classmethod
    def pip_install_cell(cls, pkg_spec):
        cmd = '!pip install -U -t /kaggle/working/ {}'.format(pkg_spec)
        return cls.make_cell(cell_type='code', source=[cmd])

    @staticmethod
    def make_cell(cell_type, **kwargs):
        """Returns a NotebookNode object populated with kwargs. cell_type should be either 'markdown' or 'code'"""
        defaults = dict(
                cell_type=cell_type,
                metadata={},
                source=[],
                )
        if cell_type == "code":
            defaults = dict(
                    execution_count=None,
                    outputs=[],
                    )
            
        defaults.update(kwargs)
        return nbformat.from_dict(defaults)
        

    def process_cell(self, cell):
        # Find all things that look like macros
        pattern = r'#\$([^$]+)\$'
        # This is one big string. It occurs to me that this is actually kind of weird
        # given that inspecting the ipynb file format, source seems to be a list of
        # strings, 1 per line (this is also what's expected by nbformat.from_dict).
        # I have no idea why this disagreement exists.
        src = cell['source']
        macros = re.finditer(pattern, src)
        newsrc = ''
        i = 0
        for match in macros:
            logging.debug(match)
            a, b = match.span()
            macro = match.group(1)
            try:
                expansion = self.expand_macro(macro, cell)
            except UnrecognizedMacroException as e:
                if IGNORE_UNKNOWN_MACROS:
                    expansion = None
                    logging.warn("Unrecognized macro: {}".format(macro))
                else:
                    raise e
            except Exception as e:
                print("Error parsing macro match {}".format(match))
                raise e
            newsrc += src[i:a]
            # Some macros might actually expand to nothing (e.g. if their purpose is to mutate cell metadata)
            if expansion:
                newsrc += expansion
            i = b
        newsrc += src[i:]
        cell['source'] = newsrc
        return cell

    def expand_macro(self, macro, cell):
        """Expand the given macro string (or apply it to the given cell, if
        it's side-effecty), by looking up and calling the corresponding
        LessonPreprocessor method.
        """
        # TODO: The fact that some macros expand to some text, and some just have
        # some effect on their cell leads to some awkwardness. Could be nice to
        # delineate syntactically. e.g. #$HIDE!$
        args = []
        if macro.endswith(')'):
            macro, argstr = macro[:-1].split('(')
            args = [argstr.strip()] if argstr.strip() else []
        macro_method = getattr(self, macro, None)
        if macro_method is None:
            raise UnrecognizedMacroException("Don't know how to handle the macro with name: {}".format(macro))
        return macro_method(*args, cell=cell)

    # TODO: Should consider separating macro logic out into separate module/class.
    def EXERCISE_FORKING_URL(self, lesson_num=None, **kwargs):
        if lesson_num is None:
            return self.lesson.exercise.forking_url
        else:
            lesson_idx = int(lesson_num) - 1
            lesson = self.track.lessons[lesson_idx]
            return lesson.exercise.forking_url

    def HIDE_INPUT(self, cell):
        cell['metadata']['_kg_hide-input'] = True

    def HIDE_OUTPUT(self, cell):
        cell['metadata']['_kg_hide-output'] = True

    def HIDE(self, cell):
        self.HIDE_INPUT(cell)
        self.HIDE_OUTPUT(cell)

    def YOURTURN(self, **kwargs):
        """Some boilerplate text to be used at the end of a tutorial notebook, to
        lead into the corresponding exercise.
        """
        return """# Your Turn

Try the [hands-on exercise]({}) with {}""".format(
        self.lesson.exercise.forking_url, self.lesson.topic
        )

    def TUT_BETA_NOTE(self, jot_id, **kwargs):
        form_url = 'https://form.jotform.com/{}'.format(jot_id)
        return """### P.S...

This course is still in beta, so I'd love to get your feedback. If you have a moment to [fill out a super-short survey about this lesson]({}), I'd greatly appreciate it. You can also leave public feedback in the comments below, or on the [Learn Forum](https://www.kaggle.com/learn-forum).
""".format(form_url)

    def EXERCISE_SETUP(self, **kwargs):
        # Standard setup code. Not currently used. Maybe should be.
        pass

    def TUTORIAL_URL(self, lesson_num=None, **kwargs):
        if lesson_num is None:
            lesson = self.lesson
        else:
            lesson_idx = int(lesson_num) - 1
            lesson = self.track.lessons[lesson_idx]
        return lesson.tutorial.url

    def EXERCISE_URL(self, lesson_num, **kwargs):
        # TODO: unify this + EXERCISE_FORKING_URL (have that be this with default arg)
        lesson_idx = int(lesson_num) - 1
        lesson = self.track.lessons[lesson_idx]
        return lesson.exercise.forking_url

    def EXERCISE_PREAMBLE(self, **kwargs):
        return """These exercises accompany the tutorial on [{}]({}).""".format(
                self.lesson.topic, self.lesson.tutorial.url,
                )

    def KEEP_GOING(self, **kwargs):

        # In "daily challenge" mode, the end of the exercise should not point to
        # the next lesson (they have to wait a day to start the next lesson)
        if self.cfg.get('daily'):
            return "\n**You'll get another email tomorrow so you can keep learning. See you then.**"
        # Don't use this macro for the very last exercise
        next_lesson = self.lesson.next
        if hasattr(next_lesson, 'tutorial'):
            next_url = next_lesson.tutorial.url
        else:
            next_url = next_lesson.exercise.forking_url

        res = """# Keep Going

You are ready for **[{}]({}).**
""".format(next_lesson.topic, next_url)

        return res

        # Alternative formulation (used on days 5 and 6 of Python challenge):
        # Want feedback on your code? To share it with others or ask for help, you'll need to make it public. Save a version of your notebook that shows your current work by hitting the "Commit & Run" button. Once your notebook is finished running, go to the Settings tab in the panel to the left (you may have to expand it by hitting the [<] button next to the "Commit & Run" button) and set the "Visibility" dropdown to "Public".

    def END_OF_EMB_EXERCISE(self, jot_id, **kwargs):
        form_url = 'https://form.jotform.com/{}'.format(jot_id)
        txt = """
---
That's the end of this exercise. How'd it go? If you have any questions, be sure to post them on the [forums](https://www.kaggle.com/learn-forum).

**P.S.** This course is still in beta, so I'd love to get your feedback. If you have a moment to [fill out a super-short survey about this exercise]({form_url}), I'd greatly appreciate it.
""".format(form_url=form_url)
        if not self.lesson.last:
            next_lesson = self.lesson.next
            kg = """
# Keep going

When you're ready to continue, [click here]({}) to continue on to the next tutorial on {}.
""".format(
        next_lesson.tutorial.url, next_lesson.topic,
        )
            txt += kg
        return txt
