# PyInstaller spec: one folder with everything (Python, numba, the avatars, the studio).
#   pyinstaller packaging/drape.spec        -> dist/drape-studio/
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
datas = [(str(ROOT / "drape" / "data"), "drape/data"),
         (str(ROOT / "drape" / "studio" / "static"), "drape/studio/static"),
         (str(ROOT / "measurements"), "drape/measurements")]
datas += collect_data_files("ezdxf") + collect_data_files("matplotlib")
hidden = collect_submodules("drape") + collect_submodules("numba") + ["scipy.spatial", "scipy.ndimage", "shapely"]

a = Analysis([str(ROOT / "packaging" / "launcher.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
             excludes=["bpy", "tkinter", "IPython", "pytest", "playwright", "cv2", "imageio_ffmpeg", "pandas", "torch"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="drape-studio", console=True,
          icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name="drape-studio")
