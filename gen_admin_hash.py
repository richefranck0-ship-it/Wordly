import getpass
from werkzeug.security import generate_password_hash
print(generate_password_hash(getpass.getpass("Mot de passe administrateur : ")))
