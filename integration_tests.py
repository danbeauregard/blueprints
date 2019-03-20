import configparser
import glob
import os
import re
import shutil
import subprocess
import sys

import yaml


regex = re.compile(r'/blueprint.ya?ml$')


def errormsg(message):
    print('ERROR: {}'.format(message))


def find_blueprint_file_directories_recursively(path=''):
    """
    Start at the given path and find all directories that contain blueprint.yml or blueprint.yaml.
    """
    blueprint_dirs = []
    for filename in glob.iglob('{}**/blueprint.y*ml'.format(path), recursive=True):
        if regex.search(filename):
            blueprint_dirs.append(regex.sub('', filename))
    return blueprint_dirs


def fail_if_missing_test_dirs(expected_test_dirs):
    missing_test_dirs = [test_dir for test_dir in expected_test_dirs if not os.path.exists(test_dir)]
    if missing_test_dirs:
        for missing_test_dir in missing_test_dirs:
            errormsg('Missing test directory {}'.format(missing_test_dir))
        sys.exit(1)


def load_testdef_from_yaml_file(yaml_file):
    """
    Given a path to a yaml, return the its contents as a dictionary.
    """
    testdef = {}
    try:
        with open(yaml_file) as contents:
            testdef = yaml.load(contents, Loader=yaml.Loader)
    except Exception as e:
        errormsg(e)
        sys.exit(1)

    return testdef


def validate_testdef(testdef):
    """
    Validate the given testdef dictionary for required keys.
    """
    if not 'answers-file' in testdef:
        errormsg("Missing 'answers-file' key in test definition")
        sys.exit(1)


def identify_missing_files(expected_files):
    """
    Extract the missing files from all those we expected to find.
    """
    return [filename for filename in expected_files if not os.path.exists('{}'.format(filename))]


def parse_xlvals_file(filepath):
    """
    Since .xlvals files are not true .ini files, we:
    - read the file contents into a string
    - prepend '[default]' to make in a valid .ini file
    - parse it as a config file
    """
    data = ""
    with open(filepath) as xlvals:
        data = '[default]\n{}'.format(xlvals.read())

    config = configparser.ConfigParser()
    config.read_string(data)
    return config


def identify_missing_xlvals(expected_xl_values, configfile):
    """
    Compare the expected values to what's been read from the config file.
    Will work with:
    - values.xlvals
    - secrets.xlvals
    """
    missing_values = {}
    for ek,ev in expected_xl_values.items():
        match = True
        if configfile.has_option('default', ek):
            val = configfile.get('default', ek)
            if ev != val:
                match = False
        else:
            match = False

        if not match:
            missing_values[ek] = ev

    return missing_values


def setup_temp_directory(dirname):
    """
    Basic setup of the disposable temp directory.
    """
    try:
        if os.path.exists(dirname):
            shutil.rmtree(dirname)
        os.mkdir(dirname, 0o755)
        if os.path.exists(dirname):
            return True
    except:
        pass
    return False


def teardown_temp_directory(dirname):
    """
    Basic teardown of the disposable temp directory.
    """
    try:
        if os.path.exists(dirname):
            shutil.rmtree(dirname)
        if not os.path.exists(dirname):
            return True
    except:
        pass
    return False


if __name__ == '__main__':
    blueprint_dirs = find_blueprint_file_directories_recursively()

    blueprint_to_test_dirs = {}
    for blueprint_dir in blueprint_dirs:
        blueprint_to_test_dirs[blueprint_dir] = '{}/__test__'.format(blueprint_dir)

    fail_if_missing_test_dirs(blueprint_to_test_dirs.values())

    for blueprint_dir, test_dir in blueprint_to_test_dirs.items():
        test_files = [filename for filename in glob.iglob('{}/test*.yaml'.format(test_dir))]
        if not test_files:
            errormsg('Missing test files under {}'.format(test_dir))
            sys.exit(1)

        env = os.environ.copy()
        env['PATH'] = '../:{}'.format(env['PATH'])

        tempdir = 'temp'

        for test_file in test_files:
            print('Processing blueprint test {}'.format(test_file))

            testdef = load_testdef_from_yaml_file(test_file)
            validate_testdef(testdef)

            answers_file = '{}/{}'.format(test_dir, testdef['answers-file'])
            if not os.path.exists(answers_file):
                errormsg('Missing answers file {} for {}'.format(answers_file, test_dir))
                sys.exit(1)

            if not setup_temp_directory(tempdir):
                errormsg('Could not creating temp directory')
                sys.exit(1)

            os.chdir(tempdir)

            command = ['xlw', 'blueprint', '-b', '../{}'.format(blueprint_dir), '-a', '../{}'.format(answers_file)]
            print('Executing {}'.format(' '.join(command)))
            result = subprocess.run(command, capture_output=True, env=env)
            if not result.returncode == 0:
                print(result.stdout)
                print('ERROR: Test failed on {} with message "{}"'.format(answers_file, result.stderr.decode('utf8').strip()))
                sys.exit(result.returncode)

            missing_files = []
            if 'expected-files' in testdef:
                missing_files = identify_missing_files(testdef['expected-files'])
            missing_xl_values = []
            if 'expected-xl-values' in testdef:
                configfile = parse_xlvals_file('xebialabs/values.xlvals')
                missing_xl_values = identify_missing_xlvals(testdef['expected-xl-values'], configfile)

            os.chdir('..')
            if not teardown_temp_directory(tempdir):
                errormsg('Could not remove temp directory')
                sys.exit(1)

            test_passed = True
            if missing_files:
                for missing_file in missing_files:
                    errormsg('Could not find expected file {}'.format(missing_file))
                test_passed = False

            if missing_xl_values:
                for mk, mv in missing_xl_values.items():
                    errormsg('Could not find expected value in values.xlvals [{} : {}]'.format(mk, mv))
                test_passed = False

            if test_passed:
                print('Test passed')
            else:
                print('Test failed')
                sys.exit(1)
