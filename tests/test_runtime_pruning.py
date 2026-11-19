import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('runtime_pruning',Path(__file__).parents[1]/'scripts/prune_runtime.py')
pruning=importlib.util.module_from_spec(spec);spec.loader.exec_module(pruning)


def fixture():
    packages={name:{'essential':False,'installed':True} for name in pruning.REMOVE}
    plan='\n'.join('Purg '+name+' [1.0]' for name in pruning.REMOVE)
    return plan,packages


def test_only_reviewed_packages_are_allowed():
    plan,packages=fixture();assert set(pruning.validate_plan(plan,packages))==pruning.REMOVE


@pytest.mark.parametrize('extra',['Remv libc6 [1.0]','Purg coreutils [1.0]','Inst unrelated (1.0)'])
def test_dependency_surprises_abort_the_image_build(extra):
    plan,packages=fixture()
    with pytest.raises(ValueError):pruning.validate_plan(plan+'\n'+extra,packages)


def test_essential_package_is_never_removed():
    plan,packages=fixture();packages['login']['essential']=True
    with pytest.raises(ValueError):pruning.validate_plan(plan,packages)
