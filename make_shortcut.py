"""Creates the app icon and a 'ReelForge' shortcut on the Desktop."""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
for y in range(S):
    for x in range(S):
        t = (x + y) / (2 * S)
        grad.putpixel((x, y), (int(124 + (255 - 124) * t), int(92 + (77 - 92) * t), int(255 + (141 - 255) * t), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([8, 8, S - 8, S - 8], radius=56, fill=255)
img.paste(grad, mask=mask)
d = ImageDraw.Draw(img)
d.polygon([(98, 70), (98, 186), (192, 128)], fill=(255, 255, 255, 255))
d.rounded_rectangle([52, 64, 72, 192], radius=6, fill=(255, 255, 255, 200))
img.save(ROOT / "app" / "static" / "icon.png")
ico = ROOT / "ReelForge.ico"
img.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
ps = f"""
$d = [Environment]::GetFolderPath('Desktop')
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'ReelForge.lnk'))
$s.TargetPath = '{pyw}'
$s.Arguments = '"{ROOT / 'launcher.pyw'}"'
$s.WorkingDirectory = '{ROOT}'
$s.IconLocation = '{ico},0'
$s.Description = 'ReelForge - AI reel & video maker'
$s.Save()
Write-Output (Join-Path $d 'ReelForge.lnk')
"""
print(subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip())
