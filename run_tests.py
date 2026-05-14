import subprocess

with open('test_output_utf8.txt', 'w', encoding='utf-8') as f:
    subprocess.run(['.venv/Scripts/pytest', 'tests/services/'], stdout=f, stderr=subprocess.STDOUT)
