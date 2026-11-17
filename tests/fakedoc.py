# SPDX-License-Identifier: AGPL-3.0-only
# A stand-in FreeCAD document for the tests of ScanRuler's state in the
# document (scanrulerfc/docstate.py) and the view keys that set FreeCAD's
# own view properties (scanrulerfc/viewprops.py): objects with properties
# and a ViewObject, a Placement as a 4 x 4 matrix, a Mesh module whose mesh
# keeps its points, and a PropertyFileIncluded that copies the file in, as
# FreeCAD's does. Installed as FreeCAD and Mesh only while a test runs
# (installed()).
import contextlib
import os
import shutil
import sys
import tempfile
import types

DEFAULTS = {"App::PropertyFileIncluded": "", "App::PropertyMap": {}, "App::PropertyInteger": 0, "App::PropertyString": "",
            "App::PropertyFloat": 0.0, "App::PropertyBool": False}


class Matrix:
    def __init__(self):
        for i in range(1, 5):
            for j in range(1, 5):
                object.__setattr__(self, f"A{i}{j}", 1.0 if i == j else 0.0)

    @property
    def A(self):
        return tuple(getattr(self, f"A{i}{j}") for i in range(1, 5) for j in range(1, 5))


class Placement:
    def __init__(self, m=None):
        self.m = m or Matrix()

    def toMatrix(self):
        return self.m


def placement(R, t):
    m = Matrix()
    for i in range(3):
        for j in range(3):
            setattr(m, f"A{i + 1}{j + 1}", float(R[i][j]))
        setattr(m, f"A{i + 1}4", float(t[i]))
    return Placement(m)


class MeshData:
    def __init__(self, data=None):
        V, F = data if data is not None else ([], [])
        self.Topology = ([tuple(p) for p in V], [tuple(f) for f in F])

    def copy(self):
        return MeshData((self.Topology[0], self.Topology[1]))


class View:
    def __init__(self):
        self.Visibility = True
        self.Transparency = 0
        self.DisplayMode = "Shaded"
        self.ShowInTree = True
        self.Proxy = None
        self.PropertiesList = ["Visibility", "Transparency", "DisplayMode", "ShowInTree"]


class Obj:
    def __init__(self, doc, type_id, name):
        d = self.__dict__
        d["Document"], d["TypeId"], d["Name"], d["Label"] = doc, type_id, name, name
        d["PropertiesList"] = ["Label", "Placement"]
        d["ViewObject"] = View()
        d["Placement"] = Placement()
        d["_files"] = set()
        if type_id == "Mesh::Feature":
            d["Mesh"] = MeshData()
        if type_id.startswith("Part::"):
            d["Group"] = []

    def addProperty(self, kind, name, group="", doc="", mode=0):
        if kind == "App::PropertyFileIncluded":
            self._files.add(name)
        self.PropertiesList.append(name)
        self.__dict__[name] = DEFAULTS.get(kind)

    def __setattr__(self, name, value):
        if name in self._files and value:
            # FreeCAD copies the file into the document's transient folder.
            folder = tempfile.mkdtemp(prefix="fakedoc-")
            to = os.path.join(folder, os.path.basename(value))
            shutil.copyfile(value, to)
            value = to
        self.__dict__[name] = value
        if name == "Mesh" and self.TypeId == "Mesh::Feature":
            # As FreeCAD's Mesh::Feature (src/Mod/Mesh/App/MeshFeature.cpp,
            # Feature::onChanged): a new mesh brings its own placement —
            # none — and the object's Placement becomes it.
            self.__dict__["Placement"] = Placement()

    @property
    def Visibility(self):
        return self.ViewObject.Visibility


class Doc:
    def __init__(self, name="Unnamed"):
        self.Name = self.Label = name
        self.Objects = []
        self.FileName = ""

    def addObject(self, type_id, name):
        taken = {o.Name for o in self.Objects}
        n, k = name, 0
        while n in taken:
            k += 1
            n = f"{name}{k:03d}"
        o = Obj(self, type_id, n)
        self.Objects.append(o)
        return o

    def getObject(self, name):
        return next((o for o in self.Objects if o.Name == name), None)

    def removeObject(self, name):
        self.Objects = [o for o in self.Objects if o.Name != name]

    def isTouched(self):
        return False

    def openTransaction(self, name):
        pass

    def commitTransaction(self):
        pass

    def abortTransaction(self):
        pass

    def recompute(self):
        pass


def modules():
    app = types.ModuleType("FreeCAD")
    app.Matrix, app.Placement = Matrix, Placement
    app.warnings = []
    app.Console = types.SimpleNamespace(PrintWarning=app.warnings.append, PrintMessage=lambda m: None)
    app.ActiveDocument = None
    mesh = types.ModuleType("Mesh")
    mesh.Mesh = MeshData
    return app, mesh


@contextlib.contextmanager
def installed():
    """FreeCAD and Mesh as these stand-ins, for the length of a with."""
    app, mesh = modules()
    saved = {k: sys.modules.get(k) for k in ("FreeCAD", "Mesh")}
    sys.modules.update({"FreeCAD": app, "Mesh": mesh})
    try:
        yield app
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
