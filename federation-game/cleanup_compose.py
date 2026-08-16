with open('docker-compose.yml', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'federation-game-root' in line or 'root-redirect' in line:
        continue
    new_lines.append(line)

with open('docker-compose.yml', 'w') as f:
    f.writelines(new_lines)
print('Cleaned up')
