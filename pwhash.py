#!/usr/bin/python3 -b

import sys
import werkzeug.security

print(werkzeug.security.generate_password_hash(sys.argv[1]))
