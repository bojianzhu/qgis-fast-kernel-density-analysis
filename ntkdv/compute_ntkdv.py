# -*- coding: utf-8 -*-
"""
NTKDV C++ Library Wrapper
"""

import ctypes
import os
import platform


def load_library(libname, loader_path):
    """Load a shared library from the specified path."""
    if ctypes.__version__ < '1.0.1':
        import warnings
        warnings.warn("All features of ctypes interface may not work "
                      "with ctypes < 1.0.1", stacklevel=2)

    ext = os.path.splitext(libname)[1]
    if not ext:
        # Try to load library with platform-specific name
        from numpy.distutils.misc_util import get_shared_lib_extension
        so_ext = get_shared_lib_extension()
        libname_ext = [libname + so_ext]
        # Mac, Windows and Linux >= py3.2 shared library and loadable
        # module have different extensions so try both
        so_ext2 = get_shared_lib_extension(is_python_ext=True)
        if not so_ext2 == so_ext:
            libname_ext.insert(0, libname + so_ext2)
    else:
        libname_ext = [libname]

    loader_path = os.path.abspath(loader_path)
    if not os.path.isdir(loader_path):
        libdir = os.path.dirname(loader_path)
    else:
        libdir = loader_path

    for ln in libname_ext:
        libpath = os.path.join(libdir, ln)
        if os.path.exists(libpath):
            try:
                return ctypes.cdll[libpath]
            except OSError:
                # Defective lib file
                raise
    # If no successful return in the libname_ext loop
    raise OSError("no file with expected extension")


# List of library names to try (Windows, Mac Intel, Mac M1)
dll_names = ['ntkdv_x86.dll', 'libntkdv_mac_x86.so', 'libntkdv_mac_M.so']

ntkdv_C_library = None
for dll_name in dll_names:
    try:
        library_path = os.path.abspath(os.path.join(os.path.dirname(__file__), dll_name))
        ntkdv_C_library = load_library(dll_name, library_path)
        break
    except Exception:
        pass

if ntkdv_C_library is None:
    raise OSError("Could not load NTKDV library. Please ensure the compiled library is available.")

# Setup the C function interface
ntkdv = ntkdv_C_library.ntkdv
ntkdv.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_char_p))
ntkdv.restype = ctypes.c_char_p


def compute_ntkdv(args):
    """
    Call the NTKDV C++ library function.
    
    Args:
        args: List of arguments encoded as ASCII bytes
        
    Returns:
        str: The result string from the C++ computation
    """
    args = (ctypes.c_char_p * len(args))(*args)
    result = ntkdv(len(args), args).decode('utf-8')
    return result

