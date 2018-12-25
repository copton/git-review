#!/usr/bin/env python

import argparse
import json
import os.path
import random
import re
import requests
import tabulate
import shlex
import string
import subprocess
import sys

################################################################################
# config
################################################################################

GIT_CONFIG_SECTION = 'review'
DEFAULT_MASTER = "master"
DEFAULT_ORIGIN = "origin"
META_VAR="PR_BRANCH"
BRANCH_TAG_LENGTH=8
WIP_TAG="wip"

################################################################################
# command line arguments
################################################################################

parser = argparse.ArgumentParser(
        description='stack-based git workflow',
        )
subparsers = parser.add_subparsers(
        title='subcommands',
        description='valid subcommands',
        dest="subcommand"
        )

parser_new = subparsers.add_parser('new', help='create a new commit')
parser_new.add_argument(
        '-j', '--jira',
        required=True,
        help=('Provide the Jira ticket number, or "HOTFIX" if you don\'t have '
              'one.\n')
        )
parser_new.add_argument(
        '-m', '--message',
        required=True,
        help='Provide the commit message (exluding the Jira prefix)\n'
        )

parser_log = subparsers.add_parser('log', help='show what is on your stack')
parser_log.add_argument(
        '-p', '--pulls',
        action='store_true',
        help='find corresponding pull requests',
        )

parser_sync = subparsers.add_parser(
        'sync', help='sync the stack branch with the master branch')

parser_rebase = subparsers.add_parser(
        'rebase', help='interactively rebase the stack branch')

parser_export = subparsers.add_parser(
    'export', help='update review branches')
#parser_export.add_argument(
#        '--all',
#        action="store_false",
#        )
#parser_export.add_argument(
#        '--commit',
#        type=str
#        )

################################################################################
# framework functions
################################################################################

# git integration
#################

def git(cmdline, inS=None, outF=None, default=None, log=False, replace=False):
  if inS is None:
    inS = ""
  if outF is None:
    outF = lambda x: x

  args = shlex.split("/usr/bin/git %s" % cmdline)
  if log:
    sys.stdout.write("git %s\n" % args[1])
  if replace:
    os.execv(args[0], args)
  proc = subprocess.Popen(
          args,
          stdin=subprocess.PIPE,
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          )
  out, err = proc.communicate(inS)
  assert proc.returncode is not None
  if proc.returncode != 0:
    if default is None:
      sys.stderr.write("git %s failed:\n%s\n" % (cmdline, err))
      sys.exit(1)
    return outF(default)
  return outF(out.strip())

# github integration
####################

def github(config, path, payload=None):
  url = 'https://api.github.com/' + path
  auth = (config.user, config.apiToken)
  if payload is None:
    r = requests.get(url, auth=auth)
    if r.status_code != 200:
      sys.stderr.write('github GET %s failed:\n%s\n' % (url, r.status_code))
      sys.exit(1)
  else:
    r = requests.post(url, auth=auth, data=payload)
    if r.status_code != 201:
      sys.stderr.write('github GET %s failed:\n%s\n' % (url, r.status_code))
      sys.exit(1)
  return r.json()

# configuration
###############

def config(key, default):
  return git(cmdline='config --local --get %(section)s.%(key)s' % {
              'section': GIT_CONFIG_SECTION,
              'key': key
              },
            default=default,
            )

class Config(object):
  def __init__(self, branch, master, origin, user, apiToken):
    self.branch = branch
    self.master = master
    self.origin = origin
    self.user = user
    self.apiToken = apiToken

def loadConfig():
    branch = config('branch', '')
    if branch == '':
      sys.stderr.write(
        ('No working branch configured. Please run:\n'
         '$ git config --local --add %(section)s.branch branch-name\n') % {
           'section': GIT_CONFIG_SECTION
           }
        )
      sys.exit(1)

    apiToken = config('api-token', '')
    if apiToken == '':
      sys.stderr.write(
        ('No API token configured. Please generate one with repo access via:\n'
         'https://github.com/settings/tokens\n'
         'and then run\n'
         '$ git config --local --add %(section)s.api-token token\n') % {
           'section': GIT_CONFIG_SECTION
           }
        )
      sys.exit(1)

    user = config('user', '')
    if user == '':
      sys.stderr.write(
        ('No Github user configured. Please run:\n'
         '$ git config --local --add %(section)s.user user\n') % {
           'section': GIT_CONFIG_SECTION
           }
        )
      sys.exit(1)

    master = config('master', DEFAULT_MASTER)
    origin = config('origin', DEFAULT_ORIGIN)

    return Config(branch, master, origin, user, apiToken)

# clean state
#############

def ensureCleanState(config):
  # Make sure we are on the working branch.
  if git('rev-parse --abbrev-ref HEAD') != config.branch:
    sys.stderr.write(
      'You must be on your working branch "%s".\n' % config.branch)
    sys.exit(1)

  # Make sure the working directory is clean.
  if git('status --porcelain') != '':
    sys.stderr.write('Your working directory is dirty.\n')
    sys.exit(1)

################################################################################
# command 'rebase'
################################################################################

def rebaseCommand(args):
  config = loadConfig()
  ensureCleanState(config)
  git('rebase --interactive --keep-empty %(master)s' % config.__dict__
     , replace=True
     )

################################################################################
# command 'sync'
################################################################################

def syncCommand(args):
  config = loadConfig()
  ensureCleanState(config)
  git('checkout %(master)s' % config.__dict__)
  git('pull --prune')
  git('checkout %(branch)s' % config.__dict__)
  git('rebase %(master)s' % config.__dict__)


################################################################################
# command 'new'
################################################################################

def newCommand(args):
  config = loadConfig()
  ensureCleanState(config)

  random.seed()
  tag = ''.join(
      random.choice(
        string.ascii_lowercase + string.digits)
        for _ in range(BRANCH_TAG_LENGTH))

  message="""%(wip)s: %(jira)s: %(message)s

%(metaVar)s=%(jira)s-%(tag)s
""" % {
    'wip': WIP_TAG,
    'jira': args.jira,
    'message': args.message,
    'metaVar': META_VAR,
    'tag': tag,
    }

  git('commit --allow-empty -F -', inS=message)

################################################################################
# command 'log'
################################################################################

metaVarPattern = re.compile(
    '^%(metaVar)s=(.*)$' % {'metaVar': META_VAR})

onelinePattern = re.compile(
    '^([^\s]*)\s(.*)$')

repoPattern = re.compile(
    '^\s*Fetch URL: git@github.com:([^/]*)/([^\.]*).git$')

class Entry(object):
  def __init__(self, commit, branch, message, pullRequest):
    self.commit = commit
    self.branch = branch
    self.message = message
    self.pullRequest = pullRequest

def reviewBranch(commit):
  def extract(message):
    for line in message.split('\n'):
      mo = metaVarPattern.match(line)
      if mo is not None:
        return mo.group(1)

  return git(
      'show -s --format=%%B %(commit)s' % {'commit': commit},
      outF=extract,
      )

def listing(config):
  def extract(lines):
    res = []
    for line in lines.split('\n'):
      if line != '':
          mo = onelinePattern.match(line)
          if mo is None:
            sys.stderr.write(
              'internal error: failed to parse --oneline representation "%s"' %
              line)
            sys.exit(1)
          res.append((mo.group(1), mo.group(2)))
    return res

  lst = git(
      'log --oneline %(master)s..%(branch)s' % config.__dict__,
      outF=extract,
      )

  res = []
  for (commit, message) in lst:
    branch = reviewBranch(commit)
    res.append(Entry(commit, branch, message, None))
  return res

def origin(config):
  def extract(lines):
    for line in lines.split('\n'):
      mo = repoPattern.match(line)
      if mo is not None:
        return (mo.group(1), mo.group(2))
    sys.stderr.write(
        'internal error: failed to finde FETCH URL in:\n%s\n' % lines)
    sys.exit(1)

  return git('remote show -n %(origin)s' % {'origin': config.origin},
             outF=extract)

def augmentedListing(config):
  lst = listing(config)
  org = origin(config)
  pullRequests = github(config, 'repos/%s/%s/pulls' % org)

  asDict = {}
  for pr in pullRequests:
    asDict[pr['head']['label']] = pr['html_url']

  for entry in lst:
    if entry.branch is not None:
      entry.pullRequest = asDict.get(org[0] + ':' + entry.branch)
  return lst

def logCommand(args):
  config = loadConfig()
  if args.pulls:
    headers = ['commit', 'branch', 'pull-request', 'message']
    data = [[e.commit, e.branch, e.pullRequest, e.message]
            for e in augmentedListing(config)]
  else:
    headers = ['commit', 'branch', 'message']
    data = [[e.commit, e.branch, e.message] for e in listing(config)]

  sys.stdout.write(tabulate.tabulate(reversed(data), headers=headers) + '\n')

################################################################################
# command 'export'
################################################################################

def createPr(config, entry):
  assert entry.pullRequest is None

  org = origin(config)
  payload = json.dumps({
    'title': entry.message,
    'body': 'Please review only the bottom-most commit',
    'head': entry.branch,
    'base': config.master,
    })

  github(config, 'repos/%s/%s/pulls' % org, payload=payload)


def export(config, entry):
  if entry.branch is None:
    sys.stdout.write(
      '%(commit)s: "%(message)s"\n\tskipping, commit has no review branch\n' %
        entry.__dict__)
    return

  if entry.message.lower().startswith(WIP_TAG):
    sys.stdout.write(
      '%(commit)s: "%(message)s"\n\tskipping, commit is work in progress\n' %
        entry.__dict__)
    return

  sys.stdout.write(
    '%(commit)s: "%(message)s"\n\texporting...\n' % entry.__dict__)
  # remove local review branch, ignore failure (if branch does not exist)
  git('branch -D %(branch)s' % entry.__dict__, default='')

  # create local review branch
  git('checkout -b %(branch)s %(commit)s' % entry.__dict__)

  # push local review branch, overwrite potentially existing upstream branch
  git('push --force --set-upstream %(origin)s %(branch)s' % {
        'branch': entry.branch, 'origin': config.origin})

  # go back to working branch
  git('checkout %(branch)s' % config.__dict__)

  # remove local review branch
  git('branch -D %(branch)s' % entry.__dict__)

  if entry.pullRequest is None:
    sys.stdout.write('\tcreating pull request...\n')
    createPr(config, entry)

def exportCommand(args):
  config = loadConfig()
  ensureCleanState(config)
  for lst in augmentedListing(config):
    export(config, lst)

################################################################################
# main
################################################################################

if __name__ == '__main__':
    args = parser.parse_args()

    func = getattr(sys.modules[__name__], args.subcommand + 'Command', None)
    if func is None:
      parser.print_help()
    else:
      func(args)

    sys.exit(0)
