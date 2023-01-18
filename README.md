# Stack-based Github workflow
We believe that small pull requests contribute to better code quality, because
both the author and reviewer can focus on a single aspect.

However, breaking up your work into small pieces, especially if you are working
on multiple issues at the same time, quickly turns into a nightmare of branches,
merges and chores. That is, if you manage a single branch per pull request.

This tool instead supports a work flow that uses only a single local working
branch, managing a single stack of commits, one per pull request.

We are constantly rebasing the stack on top of master, and we are doing more
rebasing to move hunks between commits and change the order of commits. In fact,
we are editing our code while being in an ongoing rebase.

# Workflow
First of all, let's make sure we are in sync with the latest master

    $ git review sync

Assume you want to add foo to bar next. Run

    $ git review new -j PROJ-1234 -m "Add foo to bar"

This will create a new commit for you for that specific task, tracked by the
provided Jira ticket. Now run

    $ git review rebase

and an editor opens. Put the new commit into its correct place of the stack, and
mark it with "edit". Go ahead hacking what needs to be done, then do

    $ git add -A .
    $ git rebase --continue

If you think this commit is ready for review, make sure to remove the "wip"
prefix from the commit message. Then run

    $ git review export

which will update all remote tracking branches for all commits in your stack
that are not marked with "wip", and creates a pull-request for those for which
there is none yet. See yourself with

    $ git review log -p

Follow the HTTP links to the pull requests to assign a reviewer or read the
comments.

Address your reviewer's comment by doing another

    $ git review rebase
    $ # do the work
    $ git add -A .
    $ git rebase --continue
    $ git review export

As soon as the reviewer and continuous integration are okay with your PR, merge
it through Github and delete the remote branch. Then sync with master (as
described above) and check with `git review log` that the commit is gone from
your stack.

# Caveats, known issues

1. If your reviewer has pushed a commit on the remote tracking branch, the next
`git review export` will overwrite it!

1. All pull requests go against master, so each commit that is not at the bottom
of your stack will have a pull request with all the commit below of it. Ask your
reviewer to only review that single commit, and hope they are fine with that.

# Getting started
## Installation
Create a sym-link called `git-review` that points at `git_review.py` and add it
to your PATH. Then git will find it when you run `git review`.

## Configuration

Pick a name for your working branch, let's say "stack" and run

    $ git config --local --add review.branch stack

Then, for Github integration, go to https://github.com/settings/tokens,
generate a new API token, give the token "repo" rights, and then run

    $ git config --local --add review.api-token api-token

Finally, run

    $ git config --local --add review.user github-user