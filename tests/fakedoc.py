# SPDX-License-Identifier: AGPL-3.0-only
# A stand-in FreeCAD document for the tests of ScanRuler's state in the
# document (scanrulerfc/docstate.py) and the view keys that set FreeCAD's
# own view properties (scanrulerfc/viewprops.py): objects with properties
# and a ViewObject, a Placement as a 4 x 4 matrix, a Mesh module whose mesh
# takes points and triangles the way FreeCAD's does (MeshData), and a
# PropertyFileIncluded that copies the file in, as FreeCAD's does. Installed as FreeCAD and Mesh only while a test runs
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


class Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def __len__(self):
        return 3

    def __getitem__(self, i):
        return (self.x, self.y, self.z)[i]


class MeshData:
    """A mesh that takes what FreeCAD's takes, the way FreeCAD's does
    (FreeCAD 1.1 source: src/Mod/Mesh/App/MeshPyImp.cpp, MeshPy::PyInit and
    MeshPy::addFacets; Core/MeshKernel.cpp; Core/Builder.cpp):

      a tuple (points, triangles)   the points appended as given, in
          order — but only those that are Vector objects (any other is
          passed over without a word), and each triangle must be a tuple
          (a list is a TypeError);
      a list of loose triangles     each three points: the mesh's points
          are numbered by where they first come up, equal ones are one
          point, a triangle with two equal corners is dropped.
    """

    def __init__(self, data=None):
        self.Topology = ([], [])
        if data is not None:
            self.addFacets(data)

    def addFacets(self, data, check=True):
        pts, tris = list(self.Topology[0]), list(self.Topology[1])
        if isinstance(data, tuple):
            V, F = data
            base = len(pts)
            pts += [(p.x, p.y, p.z) for p in V if isinstance(p, Vector)]
            for f in F:
                if not isinstance(f, tuple):
                    raise TypeError(f"expected a tuple, not {type(f).__name__}")
                tris.append(tuple(base + int(i) for i in f))
        elif isinstance(data, list):
            known = {p: i for i, p in enumerate(pts)}
            for t in data:
                corners = [tuple(float(x) for x in p) for p in t]
                if len(set(corners)) < 3:
                    continue
                tris.append(tuple(known.setdefault(c, len(known)) for c in corners))
            pts = sorted(known, key=known.get)
        else:
            raise TypeError(f"Cannot create a mesh out of a '{type(data).__name__}'")
        self.Topology = (pts, tris)

    @property
    def CountPoints(self):
        return len(self.Topology[0])

    @property
    def CountFacets(self):
        return len(self.Topology[1])

    def copy(self):
        m = MeshData()
        m.Topology = (list(self.Topology[0]), list(self.Topology[1]))
        return m


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
    app.Matrix, app.Placement, app.Vector = Matrix, Placement, Vector
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
