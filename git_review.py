#!/usr/bin/env python3
"""the git-review tool"""

import argparse
import json
import os
import random
import re
import shlex
import string
import subprocess
import sys
from dataclasses import dataclass

import requests
import tabulate

################################################################################
# config
################################################################################

GIT_CONFIG_SECTION = "review"
DEFAULT_MAIN = "main"
DEFAULT_ORIGIN = "origin"
META_VAR = "PR_BRANCH"
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

parser_new = subparsers.add_parser("new", help="create a new commit")
parser_new.add_argument(
    "-i",
    "--issue",
    required=True,
    help=("Provide the issue number, or 'HOTFIX' if you don't have one.\n"),
)
parser_new.add_argument(
    "-m",
    "--message",
    required=False,
    help="Provide the commit message. Default is to fetch the issue description from GitHub.\n",
)

parser_log = subparsers.add_parser("log", help="show what is on your stack")
parser_log.add_argument(
    "-p",
    "--pulls",
    action="store_true",
    help="find corresponding pull requests",
)

parser_sync = subparsers.add_parser(
    "sync", help="sync the stack branch with the main branch"
)

parser_rebase = subparsers.add_parser(
    "rebase", help="interactively rebase the stack branch"
)

parser_export = subparsers.add_parser("export", help="update review branches")
# parser_export.add_argument(
#        '--all',
#        action="store_false",
#        )
# parser_export.add_argument(
#        '--commit',
#        type=str
#        )

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


# github integration
####################


def github(config, path, payload=None):
    """Make a call to the GitHub API"""
    url = "https://api.github.com/" + path
    auth = (config.user, config.api_token)
    if payload is None:
        req = requests.get(url, auth=auth)
        if req.status_code != 200:
            sys.stderr.write(f"github GET {url} failed:\n{req.status_code}\n")
            sys.exit(1)
    else:
        req = requests.post(url, auth=auth, data=payload)
        if req.status_code != 201:
            sys.stderr.write(f"github GET {url} failed:\n{req.status_code}\n")
            sys.exit(1)
    return req.json()


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
    user: str
    api_token: str


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

    api_token = load_config("api-token", "")
    if api_token == "":
        sys.stderr.write(
            (
                "No API token configured. Please generate one with repo access via:\n"
                "https://github.com/settings/tokens\n"
                "and then run\n"
                f"$ git config --local --add {GIT_CONFIG_SECTION}.api-token token\n"
            )
        )
        sys.exit(1)

    user = load_config("user", "")
    if user == "":
        sys.stderr.write(
            (
                "No Github user configured. Please run:\n"
                f"$ git config --local --add {GIT_CONFIG_SECTION}.user user\n"
            )
        )
        sys.exit(1)

    main_branch = load_config("main", DEFAULT_MAIN)
    origin = load_config("origin", DEFAULT_ORIGIN)

    return Config(branch, main_branch, origin, user, api_token)


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
    print(config)


################################################################################
# command 'rebase'
################################################################################


def rebase_command(_args):
    """rebase on top of main"""
    config = load_all_config()
    ensure_clean_state(config)
    git(f"rebase --interactive --keep-empty {config.main}", replace=True)


################################################################################
# command 'sync'
################################################################################


def sync_command(_args):
    """sync with remote main"""
    config = load_all_config()
    ensure_clean_state(config)
    git(f"checkout {config.main}")
    git("pull --prune")
    git(f"checkout {config.branch}")
    git(f"rebase {config.main}")


################################################################################
# command 'new'
################################################################################


def new_command(args):
    """create a new commit"""
    config = load_all_config()
    ensure_clean_state(config)

    if args.message is None:
        org = remote_origin(config)
        message = github(config, f"repos/{org[0]}/{org[1]}/issues/{args.issue}")["title"]
    else:
        message = args.message

    random.seed()
    tag = "".join(
        random.choice(string.ascii_lowercase + string.digits)
        for _ in range(BRANCH_TAG_LENGTH)
    )

    message = f"""{WIP_TAG}: {args.issue}: {message}

{META_VAR}={args.issue}-{tag}
"""
    git("commit --allow-empty -F -", in_stream=message)


################################################################################
# command 'log'
################################################################################

metaVarPattern = re.compile(f"^{META_VAR}=(.*)$")

onelinePattern = re.compile(r"^([^\s]*)\s([0-9]+):\s(.*)$")

repoPattern = re.compile(r"^\s*Fetch URL: git@github.com:([^/]*)/([^\.]*).git$")


class Entry(object):
    """A log entry"""

    def __init__(self, commit, branch, issue, message):
        self.commit = commit
        self.branch = branch
        self.issue = issue
        self.message = message
        self.pull_request = None


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
                res.append((match_object.group(1), match_object.group(2), match_object.group(3)))

        return res

    lst = git(f"log --oneline {config.main}..{config.branch}", out_function=extract)

    res = []
    for (commit, issue, message) in lst:
        branch = review_branch(commit)
        res.append(Entry(commit, branch, issue, message))
    return res


def remote_origin(config):
    """determine the fetch URL of the remote 'origin'"""

    def extract(lines):
        for line in lines.split("\n"):
            match_object = repoPattern.match(line)
            if match_object is not None:
                return (match_object.group(1), match_object.group(2))
        sys.stderr.write(f"internal error: failed to finde FETCH URL in:\n{lines}\n")
        sys.exit(1)

    return git(f"remote show -n {config.origin}", out_function=extract)


def augmented_listing(config):
    """git log with augmented information"""
    lst = listing(config)
    org = remote_origin(config)
    pull_requests = github(config, f"repos/{org[0]}/{org[1]}/pulls")

    as_dict = {}
    for pull_request in pull_requests:
        as_dict[pull_request["head"]["label"]] = pull_request["html_url"]

    for entry in lst:
        if entry.branch is not None:
            entry.pull_request = as_dict.get(org[0] + ":" + entry.branch)
    return lst


def log_command(args):
    """git log of the stack"""
    config = load_all_config()
    if args.pulls:
        headers = ["commit", "branch", "pull-request", "issue", "message"]
        data = [
            [e.commit, e.branch, e.pull_request, e.issue, e.message]
            for e in augmented_listing(config)
        ]
    else:
        headers = ["commit", "branch", "issue", "message"]
        data = [[e.commit, e.branch, e.issue, e.message] for e in listing(config)]

    sys.stdout.write(tabulate.tabulate(reversed(data), headers=headers) + "\n")


################################################################################
# command 'export'
################################################################################


def create_pull_request(config, entry):
    """create a new pull request"""
    assert entry.pull_request is None

    org = remote_origin(config)
    payload = json.dumps(
        {
            "title": entry.message,
            "body": f"Closes #{entry.issue}" if entry.issue else "",
            "head": entry.branch,
            "base": config.main,
        }
    )

    github(config, f"repos/{org[0]}/{org[1]}/pulls", payload=payload)


def export(config, entry):
    """export the commits as merge requests"""
    if entry.branch is None:
        sys.stdout.write(
            f'{entry.commit}: "{entry.message}"\n\tskipping, commit has no review branch\n'
        )
        return

    if entry.message.lower().startswith(WIP_TAG):
        sys.stdout.write(
            f'{entry.commit}: "{entry.message}"\n\tskipping, commit is work in progress\n'
        )
        return

    sys.stdout.write(f'{entry.commit}: "{entry.message}"\n\texporting...\n')
    # remove local review branch, ignore failure (if branch does not exist)
    git(f"branch -D {entry.branch}", default="")

    # create local review branch
    git(f"checkout -b {entry.branch} {entry.commit}")

    # push local review branch, overwrite potentially existing upstream branch
    git(f"push --force --set-upstream {config.origin} {entry.branch}")

    # go back to working branch
    git(f"checkout {config.branch}")

    # remove local review branch
    git(f"branch -D {entry.branch}")

    if entry.pull_request is None:
        sys.stdout.write("\tcreating pull request...\n")
        create_pull_request(config, entry)


def export_command(_args):
    """export all non-wip commits of the stack to the origin"""
    config = load_all_config()
    ensure_clean_state(config)
    for lst in augmented_listing(config):
        export(config, lst)


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
