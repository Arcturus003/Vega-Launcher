import os
import shutil

src_dir = os.getcwd()
dest_dir1 = os.path.join(src_dir, 'build_out', 'main')
dest_dir2 = os.path.join(src_dir, 'build_out', 'main', '_internal')

assets = ['style.qss', 'bg.jpg', 'enderman_icon.ico', 'assets', '.integrity', 'credentials.json']

for dest_dir in [dest_dir1, dest_dir2]:
    for item in assets:
        s = os.path.join(src_dir, item)
        d = os.path.join(dest_dir, item)
        if os.path.exists(s):
            if os.path.isdir(s):
                if os.path.exists(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
print('Assets copied successfully to both dirs!')
