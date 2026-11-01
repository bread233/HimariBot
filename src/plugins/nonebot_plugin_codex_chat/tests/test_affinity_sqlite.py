"""Real SQLite affinity tests using a temporary database, never production data."""
import importlib.util
import math
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "maibot_core" / "common" / "database"


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AffinitySQLiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from sqlmodel import SQLModel, Session, create_engine, select
        except ImportError as exc:
            raise unittest.SkipTest(f"SQLModel/SQLAlchemy unavailable: {exc}")
        cls.Session = Session
        cls.select = select
        cls.SQLModel = SQLModel
        cls.tmp = tempfile.TemporaryDirectory(prefix="himari_affinity_test_")
        cls.engine = create_engine("sqlite:///" + str(Path(cls.tmp.name) / "test.db"), connect_args={"check_same_thread": False})
        cls.model_module = load_file("himari_sqlite_test_model", DB_DIR / "database_model.py")
        cls.Model = cls.model_module.HimariBotAffinity
        SQLModel.metadata.create_all(cls.engine, tables=[cls.Model.__table__])

        @contextmanager
        def test_session():
            with Session(cls.engine) as session:
                try:
                    yield session
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise

        cls.test_session = staticmethod(test_session)
        fake_src = types.ModuleType("src")
        fake_src.__path__ = []
        fake_common = types.ModuleType("src.common")
        fake_common.__path__ = []
        fake_db_pkg = types.ModuleType("src.common.database")
        fake_db_pkg.__path__ = []
        fake_db = types.ModuleType("src.common.database.database")
        fake_db.get_db_session = test_session
        fake_model = types.ModuleType("src.common.database.database_model")
        fake_model.HimariBotAffinity = cls.Model
        cls.modules = {
            "src": fake_src, "src.common": fake_common,
            "src.common.database": fake_db_pkg,
            "src.common.database.database": fake_db,
            "src.common.database.database_model": fake_model,
        }
        cls.module_patch = patch.dict(sys.modules, cls.modules)
        cls.module_patch.start()
        cls.store = load_file("himari_sqlite_test_store", DB_DIR / "affinity_store.py")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "module_patch"):
            cls.module_patch.stop()
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "tmp"):
            cls.tmp.cleanup()

    def setUp(self):
        with self.test_session() as session:
            session.query(self.Model).delete()

    def test_initial_value_and_repeated_get(self):
        first = self.store.get_or_create_affinity("10001")
        second = self.store.get_or_create_affinity("10001")
        self.assertEqual(first.affinity_score, 10)
        self.assertEqual(second.affinity_score, 10)
        with self.test_session() as session:
            self.assertEqual(session.query(self.Model).count(), 1)

    def test_persistence_across_sessions(self):
        self.store.change_affinity("10002", 7)
        with self.test_session() as session:
            record = session.get(self.Model, "10002")
            self.assertEqual(record.affinity_score, 17)
            self.assertEqual(record.interaction_count, 1)

    def test_positive_and_negative_delta(self):
        self.assertEqual(self.store.change_affinity("10003", 5).affinity_score, 15)
        self.assertEqual(self.store.change_affinity("10003", -8).affinity_score, 7)

    def test_score_upper_and_lower_bounds(self):
        self.assertEqual(self.store.change_affinity("10004", 1000).affinity_score, 100)
        self.assertEqual(self.store.change_affinity("10004", -1000).affinity_score, -20)

    def test_invalid_qq_and_nonfinite_delta(self):
        for qq in ("", "abc", "-5"):
            with self.subTest(qq=qq), self.assertRaises(ValueError):
                self.store.get_or_create_affinity(qq)
        for delta in (math.nan, math.inf, -math.inf):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                self.store.change_affinity("10005", delta)

    def test_interaction_counter_and_timestamp(self):
        self.store.change_affinity("10006", 1)
        result = self.store.change_affinity("10006", 2)
        self.assertEqual(result.interaction_count, 2)
        self.assertIsNotNone(result.last_interaction_at)

    def test_failed_transaction_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with self.test_session() as session:
                session.add(self.Model(qq_id="10007", affinity_score=42))
                session.flush()
                raise RuntimeError("force rollback")
        with self.test_session() as session:
            self.assertIsNone(session.get(self.Model, "10007"))


if __name__ == "__main__":
    unittest.main()
