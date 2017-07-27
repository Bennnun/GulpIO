from pybuilder.core import use_plugin, init

use_plugin("python.core")
use_plugin("python.unittest")
use_plugin("python.install_dependencies")
use_plugin("python.flake8")
use_plugin("python.coverage")
use_plugin("python.distutils")


name = "gulpio"
default_task = "publish"


@init
def set_properties(project):
    project.set_property('coverage_break_build', False)
    project.depends_on('tqdm')
    project.depends_on('opencv-python')
    project.depends_on('pandas')
    project.depends_on('docopt')
    project.depends_on('joblib')
    project.depends_on('Pillow')
    project.depends_on('sh')

