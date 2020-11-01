# Balancing Valorisation Platform (BVP)

This is Seita's implementation of the BVP pilot for A1.

The *Balancing Valorisation Platform (BVP)* is a tool for scheduling balancing actions on behalf of the connected asset owners.
Its purpose is to offer these balancing actions as one aggregated service to energy markets, realising the highest possible value for its users.


## Build & Run


### Dependencies

Install dependencies and the `bvp` platform itself:

      make install

### Configure environment

* Set an env variable to indicate in which environment you are operating (one out of development|testing|staging|production), e.g.:

    `echo "FLASK_ENV=development" >> .env`

    `export FLASK_ENV=production`
* If you need to customise settings, create `bvp/<development|testing|staging|production>_config.py` and add required settings.
  If you're unsure what you need, just continue for now and the app will tell you what it misses.

### Make a secret key for sessions

    mkdir -p /path/to/bvp/instance
    head -c 24 /dev/urandom > /path/to/bvp/instance/secret_key

### Preparing a database

* Make sure you have a Postgres (Version 9+) database. See `data/Readme.md` for instructions on this.
* Tell `bvp` about it. Either you are using the default for the environment you're in (see `bvp/utils/config_defaults`),
   or you can configure your own connection string: In `bvp/<development|testing|staging|production>_conf.py`,
  set the variable `SQLALCHEMY_DATABASE_URI = 'postgresql://<user>:<password>@<host-address>[:<port>]/<db>'`
* Run `flask db upgrade` to create the Postgres DB structure.

### Install an LP solver

For planning balancing actions, the BVP platform uses a linear program solver. Currently that is the Cbc solver. See the `BVP_LP_SOLVER` config setting if you want to change to a different solver.

Installing Cbc can be done on Unix via:

    apt-get install coinor-cbc
    
(also available in different popular package managers).

We provide a script for installing from source (without requiring `sudo` rights) in [the CI Readme](ci/Readme.md).

More information (e.g. for installing on Windows) on [the website](https://projects.coin-or.org/Cbc).


### Run

Now, to start the web application, you can run:

    python bvp/run-local.py

But in a production context, you shouldn't run a script - hand the `app` object to a WSGI process, as your platform of choice describes.

Often, that requires a WSGI script. We provide an example WSGI script in [the CI Readme](ci/Readme.md).


## Loading data

If you have a SQL Dump file, you can load that:

    psql -U {user_name} -h {host_name} -d {database_name} -f {file_path}

Else, you can populate some standard data, most of which comes from files:

* Finally, run `flask db_populate --structure --data --small` to load this data into the database.
  The `--small` parameter will only load four assets and four days, so use this first to try things out. TODO: check which command is possible at the moment. Also add a TODO saying where we want to go with this (support for loading data).


## Developing

Note: For developers, there is more detailed documentation available. Please consult the documentation next to the relevant code:

* [General coding tips and maintenance](bvp/README.md)
* [Continuous Integration](ci/README.md)
* [Database management](bvp/data/Readme.md)
* [API development](bvp/api/Readme.md)


### Virtual environment

* Make a virtual environment: `python3.8 -m venv bvp-venv` or use a different tool like `mkvirtualenv` or virtualenvwrapper. You can also use
  an [Anaconda distribution](https://conda.io/docs/user-guide/tasks/manage-environments.html) as base with `conda create -n bvp-venv python=3.8`.
* Activate it, e.g.: `source bvp-venv/bin/activate`


### Dependencies

Install all dependencies including the ones needed for development:

    make install-for-dev

### Run locally

Now, to start the web application, you can run:

    python bvp/run-local.py

And access the server at http://localhost:5000


### Tests

You can run automated tests with:

    make test

which behind the curtains installs dependencies and calls pytest.

A coverage report can be created like this:

    pytest --cov=bvp --cov-config .coveragerc

You can add --cov-report=html after which a htmlcov/index.html is generated.

It's also possible to use:

    python setup.py test
