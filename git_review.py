#!/usr/bin/env python3
"""the git-review tool"""

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass

import tabulate

################################################################################
# config
################################################################################

GIT_CONFIG_SECTION = "review"
DEFAULT_MAIN = "main"
DEFAULT_ORIGIN = "origin"
META_VAR = "BRANCH"
BRANCH_TAG_LENGTH = 8
WIP_TAG = "wip"

################################################################################
# command line arguments
################################################################################

parser = argparse.ArgumentParser(
    description="stack-based git workflow",
)
subparsers = parser.add_subparsers(
    title="subcommands", description="valid subcommands", dest="subcommand"
)

subparsers.add_parser("config", help="print the config")

subparsers.add_parser("push", help="push the local branch to remote")

parser_new = subparsers.add_parser("new", help="create a new commit")
parser_new.add_argument(
    "-b",
    "--branch",
    metavar="branch-prefix",
    required=True,
    help=(
        "The prefix of the name of the review branch for the future pull request."
        "we will add to it the ticket number and the git message"
    ),
)
parser_new.add_argument(
    "-t",
    "--ticket",
    required=True,
    help="The ticket number associated with this commit.",
)
parser_new.add_argument(
    "-m",
    "--message",
    required=True,
    help="The commit message\n",
)
parser_log = subparsers.add_parser("log", help="show what is on your stack")

parser_sync = subparsers.add_parser(
    "sync", help="sync the stack branch with the main branch"
)

parser_rebase = subparsers.add_parser(
    "rebase", help="interactively rebase the stack branch"
)

parser_export = subparsers.add_parser("export", help="update bottom most review branch")

################################################################################
# framework functions
################################################################################

# git integration
#################


def git(cmdline, in_stream=None, out_function=None, default=None, replace=False):
    """Execute git commands"""
    if in_stream is None:
        in_stream = ""
    if out_function is None:
        out_function = lambda x: x

    args = shlex.split(f"/usr/bin/git {cmdline}")
    if replace:
        os.execv(args[0], args)
    with subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        out, err = proc.communicate(in_stream.encode("utf-8"))
        assert proc.returncode is not None
        if proc.returncode != 0:
            if default is None:
                sys.stderr.write(f"git {cmdline} failed:\n{err.decode('utf-8')}\n")
                sys.exit(1)
            return out_function(default)
        return out_function(out.decode("utf-8").strip())


# configuration
###############


def load_config(key, default):
    """Load the git config relevant to this tool"""
    return git(
        cmdline=f"config --local --get {GIT_CONFIG_SECTION}.{key}",
        default=default,
    )


@dataclass
class Config:
    """Config of this tool"""

    branch: str
    main: str
    origin: str


def load_all_config():
    """Load this tool's config"""
    branch = load_config("branch", "")
    if branch == "":
        sys.stderr.write(
            (
                "No working branch configured. Please run:\n"
                f"$ git config --local --add {GIT_CONFIG_SECTION}.branch branch-name\n"
            )
        )
        sys.exit(1)

    main_branch = load_config("main", DEFAULT_MAIN)
    origin = load_config("origin", DEFAULT_ORIGIN)

    return Config(branch, main_branch, origin)


# clean state
#############


def ensure_clean_state(config):
    """make sure the working directory is in a clean state"""
    # Make sure we are on the working branch.
    if git("rev-parse --abbrev-ref HEAD") != config.branch:
        sys.stderr.write(f'You must be on your working branch "{config.branch}".\n')
        sys.exit(1)

    # Make sure the working directory is clean.
    if git("status --porcelain") != "":
        sys.stderr.write("Your working directory is dirty.\n")
        sys.exit(1)


################################################################################
# command 'config'
################################################################################


def config_command(_args):
    """print the configuration"""
    config = load_all_config()
    sys.stdout.write(str(config))


################################################################################
# command 'push'
################################################################################


def push_command(_args):
    """push the local branch to remote"""
    config = load_all_config()
    ensure_clean_state(config)
    git(f"push --force --set-upstream {config.origin} {config.branch}")


################################################################################
# command 'rebase'
################################################################################


def rebase_command(_args):
    """rebase on top of main"""
    config = load_all_config()
    ensure_clean_state(config)
    git(
        f"rebase --interactive --keep-empty {config.origin}/{config.main}", replace=True
    )


################################################################################
# command 'sync'
################################################################################


def sync_command(_args):
    """sync with remote main"""
    config = load_all_config()
    ensure_clean_state(config)
    git(f"fetch {config.origin} {config.main}")
    git(f"rebase --keep-empty {config.origin}/{config.main}")


################################################################################
# command 'new'
################################################################################


def new_command(args):
    """create a new commit"""
    config = load_all_config()
    ensure_clean_state(config)

    msg = re.sub("[^0-9a-zA-Z]+", "-", args.message)
    branch = f"{args.branch}/{args.ticket}-{msg}"
    message = f"""{WIP_TAG}: {args.message}

{META_VAR}={branch}
"""
    git("commit --allow-empty -F -", in_stream=message)


################################################################################
# command 'log'
################################################################################

metaVarPattern = re.compile(f"^{META_VAR}=(.*)$")

onelinePattern = re.compile(r"^([^\s]*)\s(.*)$")


class Entry(object):
    """A log entry"""

    def __init__(self, commit, branch, message):
        self.commit = commit
        self.branch = branch
        self.message = message


def review_branch(commit):
    """determine the review branch of a commit"""

    def extract(message):
        for line in message.split("\n"):
            match_object = metaVarPattern.match(line)
            if match_object is not None:
                return match_object.group(1)

    return git(f"show -s --format=%B {commit}", out_function=extract)


def listing(config):
    """list all commits of the stack"""

    def extract(lines):
        res = []
        for line in lines.split("\n"):
            if line != "":
                match_object = onelinePattern.match(line)
                if match_object is None:
                    sys.stderr.write(
                        f'internal error: failed to parse --oneline representation "{line}"'
                    )
                    sys.exit(1)
                res.append((match_object.group(1), match_object.group(2)))
        return res

    lst = git(
        f"log --oneline {config.origin}/{config.main}..{config.branch}",
        out_function=extract,
    )

    res = []
    for commit, message in lst:
        branch = review_branch(commit)
        res.append(Entry(commit, branch, message))
    return res


def log_command(args):
    """git log of the stack"""
    config = load_all_config()
    headers = ["commit", "branch", "message"]
    data = [[e.commit, e.branch, e.message] for e in listing(config)]

    sys.stdout.write(tabulate.tabulate(reversed(data), headers=headers) + "\n")


################################################################################
# command 'export'
################################################################################


def export(config, entry):
    """export the entry as merge requests"""
    if entry.branch is None:
        sys.stdout.write(
            f'export failed: {entry.commit} - "{entry.message}": commit has no review branch\n'
        )
        return

    if entry.message.lower().startswith(WIP_TAG):
        sys.stdout.write(
            f'export failed: {entry.commit} - "{entry.message}": commit is marked as work in progress\n'
        )
        return

    sys.stdout.write(f'exporting {entry.commit} - "{entry.message}"\n')

    # # remove local review branch, ignore failure (if branch does not exist)
    git(f"branch -D {entry.branch}", default="")

    # # create local review branch
    git(f"checkout -b {entry.branch} {entry.commit}")

    # # push local review branch, overwrite potentially existing upstream branch
    git(f"push --force --set-upstream {config.origin} {entry.branch}")

    # # go back to working branch
    git(f"checkout {config.branch}")

    # # remove local review branch
    git(f"branch -D {entry.branch}")


def export_command(_args):
    """export all non-wip commits of the stack to the origin"""
    config = load_all_config()
    ensure_clean_state(config)
    entries = listing(config)
    if len(entries) == 0:
        sys.stdout.write("no commits to export")
        return
    export(config, entries[-1])


################################################################################
# main
################################################################################


def main():
    """The main function"""
    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        sys.exit(0)

    func = getattr(sys.modules[__name__], args.subcommand + "_command", None)
    if func is None:
        parser.print_help()
        sys.exit(0)

    func(args)


if __name__ == "__main__":
    main()
