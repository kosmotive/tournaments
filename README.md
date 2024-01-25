# tournaments

## Management and development

**This is required only once for inital setup.**

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

Change into the `tournaments` directory:
```
cd tournaments
```

### Reset the database

**This is only required when migrations cannot be performed.**

Reset database migrations:
```bash
rm db.sqlite3
rm -rf */migrations
```

### Initialize the database

**This is only required after initial setup or after resetting the database.**

Create migrations:
```bash
python manage.py makemigrations
```

Create database:
```bash
python manage.py migrate
```

Create a superuser:
```bash
python manage.py createsuperuser
```

### Day-to-day use

Run tests:
```bash
python manage.py test
```

Run the local server:
```bash
python manage.py runserver
```
