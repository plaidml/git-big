[![Build Status](https://travis-ci.org/vertexai/git-big.svg?branch=master)]()
# git-big

Git Big is a command line extension to Git for managing
[Write Once Read Many (WORM)](https://en.wikipedia.org/wiki/Write_once_read_many) files.

## Requirements

* A filesystem that supports symbolic & hard linking (Linux, MacOS, Windows/NTFS)
* Python 2.7 or Python 3.6
* (optional) An account with one of the 
  [storage providers](https://libcloud.readthedocs.io/en/latest/storage/supported_providers.html)
  supported by [Apache Libcloud](https://libcloud.apache.org/):
  * Amazon S3
  * Google Cloud Storage
  * Microsoft Azure

## Getting Started

Use `pip` to install `git-big`:

```
pip install git-big
```

Next, go to the directory root of your Git repository and initialize `git-big`:

```
git big init
```

A user configuration file is located at `$HOME/.gitbig`.
Its contents look something like:

```
{
    "version": 1,
    "cache_dir": "/home/user/.cache/git-big",
    "depot": {
        "url": "s3://bucket_name/path",
        "key": "XXXX",
        "secret": "XXXX"
    }
}
```

You may optionally configure a depot which is a backend for storing
content-addressable objects in a centralized and sharable location.
[Apache Libcloud](https://libcloud.apache.org/) is used for accessing
object storage from a variety of providers.
See the
[supported providers matrix](https://libcloud.readthedocs.io/en/latest/storage/supported_providers.html)
for specifics on configuring a particular provider.

A `.gitbig` index file also exists in the root of the Git repository.
This file should be checked into your repository.
Here's an example of such a file.

```
{
    "version": 1,
    "files": {
        "some/path/to/file1": "be6e6f89cb50b25616c5c1d5e2451f03e83a42c1effdd18bde29723354f00ae6",
        "some/path/to/file2": "be6e6f89cb50b25616c5c1d5e2451f03e83a42c1effdd18bde29723354f00ae6",
        "some/other/file": "d75aedd9e4df46b9c879819c6973c723e791fc78106238b5e516bf9d42675af4"
    }
}
```

## Usage

A typical Git Big workflow might look like this:

```
# Initialize the repository
$ git big init

# Add a big file
$ git big add bigfile.iso
bigfile.iso

# The file has been added to the index
$ git big status
On branch master

  Working
    Cache
      Depot

[ W C   ] 993328d6 bigfile.iso

# A sha256 hash is generated and recorded in the index
$ cat .gitbig
{
    "files": {
        "bigfile.iso": "993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4"
    }, 
    "version": 1
}

# Note that the big file is now a symlink
$ ls -l bigfile.iso
lrwxrwxrwx 1 user user 8 Jun  9 13:14 bigfile.iso -> .gitbig-anchors/99/33/993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4

# And that the symlink points to a read-only file
$ ls -l $(readlink bigfile.iso)
-r--r--r-- 2 user user 8 Jun  9 13:39 .gitbig-anchors/99/33/993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4

# Push any pending big files to the depot
$ git big push
Pushing object: 993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4

# We can see the big file has been archived in the depot
$ git big status
On branch master

  Working
    Cache
      Depot

[ W C D ] 993328d6 bigfile.iso

# Now we can commit our changes
$ git commit -m "Add bigfile.iso"
[master (root-commit) 93e6c96] Add bigfile.iso
 2 files changed, 7 insertions(+)
 create mode 100644 .gitbig
 create mode 120000 bigfile.iso

# And push them upstream
$ git push origin master

# Now let's clone this repository onto another machine
$ git clone git@git-repo:repo.git
$ cd repo

# Initially, the big file will only exist in the depot
$ git big status
On branch master

  Working
    Cache
      Depot

[     D ] 993328d6 bigfile.iso

# Let's pull it from the depot (caching it as we go)
$ git big pull
Pulling object: 993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4

# Note that the symlink now points to a read-only file and has a reference count of 2 (the other ref is in the cache)
$ ls -l $(readlink bigfile.iso)
-r--r--r-- 2 user user 8 Jun 12 23:30 .gitbig-anchors/99/33/993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4

# It's now ready to be used
$ git big status
On branch master

  Working
    Cache
      Depot

[ W C D ] 993328d6 bigfile.iso
```

## Reference

```
Usage: git-big [OPTIONS] COMMAND [ARGS]...

  git big file manager

Options:
  -h, --help  Show this message and exit.

Commands:
  add
    Add big files. Each specified path will be added to git-big. If a path
    refers to a directory, all files within the directory will be recursively
    added to the index.

  clone
    Clone a repository with big files.

  cp
    Copy big files. Copies a big file in the same way that git cp would
    usually work. The index will be updated to refer to the old and new
    location of copied files.

  help
    Show this message and exit.

  init
    Initialize a repository.

  mv
    Move big files. Moves a big file in the same way that git mv would usually
    work. The index will be updated to refer to the new location of moved files.

  pull
    Pull big files. Downloads big files from any configured depot.

  push
    Push big files. Uploads big files to any configured depot.

  rm
    View big file status. Shows the status of each file recognized by git-big.
    path refers to a directory, all files within the directory will be
    recursively removed from the index.

  status
    View big file status. Shows the status of each file recognized by git-big.

  unlock
    Unlock big files. When a file is added to git-big, the working copy is set
    to read-only mode to prevent from accidental overwrites or deletions. Use
    this command to allow the file to be modified. The file must be added back
    to git-big when changes are complete.

  version
    Print version and exit.
```
