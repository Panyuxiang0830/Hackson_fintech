import unittest

from src.data import load_documents, load_users
from src.policy import PolicyEngine


class PolicyEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.users = load_users()
        cls.documents = {document.id: document for document in load_documents()}
        cls.policy = PolicyEngine()

    def test_engineer_can_read_restricted_engineering_incident(self):
        decision = self.policy.evaluate(self.users["alice"], self.documents["jira-002"])
        self.assertTrue(decision.allowed)

    def test_operations_cannot_read_restricted_engineering_incident(self):
        decision = self.policy.evaluate(self.users["bob"], self.documents["jira-002"])
        self.assertFalse(decision.allowed)

    def test_contractor_cannot_read_project_internal_document(self):
        decision = self.policy.evaluate(self.users["dave"], self.documents["release-001"])
        self.assertFalse(decision.allowed)

    def test_public_overview_is_available_to_contractor(self):
        decision = self.policy.evaluate(self.users["dave"], self.documents["public-001"])
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()

