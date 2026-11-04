import azulejos_tablet.rhino_link_backup as rhino_link_backup

code = """
import sys
print("AZULEJOS: " + str(sys.version_info[:3]))
"""

print(rhino_link_backup.run_python(code))