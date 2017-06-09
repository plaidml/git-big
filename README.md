# git-big

Git Big is a command line extension to Git for managing
[Write Once Read Many (WORM)](https://en.wikipedia.org/wiki/Write_once_read_many) files.

## Requirements

* A filesystem that supports hard-linking (Linux & MacOS, Windows is untested)
* Python 2.7+
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
Its contents looks something like:

```
{
    "version": 1,
    "cache_dir": "/home/user/.cache/git-big",
    "depot": {
        "driver": "s3",
        "bucket": "bucket_name",
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

A configuration file also exists in the root of the Git repository.
This file should be checked into your repository.
Repository configuration overrides any user configuration.
Here's an example of the `.gitbig` repository configuration file.

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

# The file has been added to the index
$ git big status
On branch master

  Working
    Linked
      Cache
        Depot

[ W       ] bigfile.iso

# A sha256 hash is generated and recorded in the index
$ cat .gitbig
{
    "files": {
        "bigfile.iso": "993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4"
    }, 
    "version": 1, 
    "tracking": {}
}

# Note that the bigfile is now read-only
$ ls -l bigfile.iso
-r--r--r-- 1 user user 8 Jun  9 13:14 bigfile.iso

# git-big will automatically create a .gitignore rule
$ cat .gitignore
/bigfile.iso

# Push any pending bigfiles to the cache and to the depot
$ git big push
Linking: bigfile.iso -> 993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4
Pushing object: 993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4

# We can see the bigfile has been cached and archived in the depot
$ git big status
On branch master

  Working
    Linked
      Cache
        Depot

[ W L C D ] bigfile.iso

# Now we can commit and push our changes to the git repository
$ git add -A
$ git ci -m "Add bigfile.iso"
[master (root-commit) 7679004] Add bigfile.iso
 2 files changed, 8 insertions(+)
 create mode 100644 .gitbig
 create mode 100644 .gitignore
$ git push origin master

# Now let's clone this repository onto another machine
$ git clone git@git-repo:demo.git
$ git big init

# Initially, the bigfile will not exist in the working directory
$ ls bigfile.iso
ls: cannot access 'bigfile.iso': No such file or directory

# But it does exist in the depot
$ git big status
On branch master

  Working
    Linked
      Cache
        Depot

[       D ] bigfile.iso

# Let's pull it from the depot (caching it as we go)
$ git big pull
Pulling object: 993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4
Linking: 993328d6ae3506d656f4d7ad3edf917a7d86f61ef9e01a0f177683b5961893b4 -> bigfile.iso

# Note that the file is read-only and has a reference count of 2 (the other ref is in the cache)
$ ls -l bigfile.iso
-r--r--r-- 2 user user 8 Jun  9 13:39 bigfile.iso

# It's now ready to be used
$ git big status
On branch master

  Working
    Linked
      Cache
        Depot

[ W L C D ] bigfile.iso
```

## Reference

```
Usage: git-big [OPTIONS] COMMAND [ARGS]...

  git big file manager

Options:
  -h, --help  Show this message and exit.

Commands:
  add      Add big files
  cp       Copy big files
  help     Show this message and exit.
  init     Initialize big files
  mv       Move big files
  pull     Pull big files
  push     Push big files
  rm       Remove big files
  status   View big file status
  unlock   Unlock big files
  version  Print version and exit
```
