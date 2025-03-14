<div align="center">
  <h1><a href="https://github.com/kostrykin/tournaments">tournaments</a><br>
  <a href="https://github.com/kostrykin/tournaments/actions/workflows/testsuite.yml"><img src="https://github.com/kostrykin/tournaments/actions/workflows/testsuite.yml/badge.svg"></a>
  <a href="https://github.com/kostrykin/tournaments/actions/workflows/testsuite.yml"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/kostrykin/bb85310a74d6b05330d230443007b878/raw/tournaments.json" /></a>
  </h1>
</div>

## Screenshots

<div align="center">
<p><kbd><img width="1128" src="https://github.com/kostrykin/tournaments/assets/6557139/44c98a04-8613-447a-82fa-30abede06ea3"></kbd></p>
<p><kbd><img width="1128" src="https://github.com/kostrykin/tournaments/assets/6557139/4fefa3b0-8b98-47bf-9a7e-8812d8f3064a"></kbd></p>
</div>

## Installation

### Initial setup

Create virtual environment:
```bash
python -m venv venv
```
Activate virtual environment:
```bash
source venv/bin/activate
```

Install dependencies into virtual environment:
```bash
pip install -r requirements.txt
```

#### Prerequisites after initial setup

Activate virtual environment: (if not done yet)
```bash
source venv/bin/activate
```

Change into the `tournaments` directory:
```
cd tournaments
```

#### Initialize/update the database

This is only required after the initial setup, or when updating to new versions:

1. Create/update the database:
    ```bash
    python manage.py migrate
    ```

2. Create a superuser: (only after the initial setup)
    ```bash
    python manage.py createsuperuser
    ```

#### Day-to-day use

Run tests:
```bash
python manage.py test
```

Compute test coverage:
```bash
coverage run --source='.' manage.py test
coverage html
```
This assumes that *coverage.py* was installed (e.g., `pip install coverage`).

Run the local server:
```bash
python manage.py runserver
```
