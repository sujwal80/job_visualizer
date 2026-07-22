import unittest
import os
from unittest import mock
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend import config

class TestConfigPlatform(unittest.TestCase):
    def setUp(self):
        # Save original env
        self.original_environ = dict(os.environ)
        # Reset config to clean state
        config.setup_config(None)

    def tearDown(self):
        # Restore original env
        os.environ.clear()
        os.environ.update(self.original_environ)
        config.setup_config(None)

    def test_fallback_to_os_environ(self):
        # Modify os.environ
        os.environ["GOOGLE_CLIENT_ID"] = "env_google_client_id"
        os.environ["JWT_SECRET_KEY"] = "env_jwt_secret_key"
        
        config.setup_config(None)
        
        self.assertEqual(config.GOOGLE_CLIENT_ID, "env_google_client_id")
        self.assertEqual(config.JWT_SECRET_KEY, "env_jwt_secret_key")

    def test_override_by_env_object(self):
        # Create a mock env object with bindings
        class MockEnv:
            def __init__(self):
                self.GOOGLE_CLIENT_ID = "cf_google_client_id"
                self.JWT_SECRET_KEY = "cf_jwt_secret_key"
                
        mock_env = MockEnv()
        config.setup_config(mock_env)
        
        self.assertEqual(config.GOOGLE_CLIENT_ID, "cf_google_client_id")
        self.assertEqual(config.JWT_SECRET_KEY, "cf_jwt_secret_key")

    def test_override_by_env_dict(self):
        # Create a mock env dict
        mock_env = {
            "GOOGLE_CLIENT_ID": "cf_dict_google_client_id",
            "JWT_SECRET_KEY": "cf_dict_jwt_secret_key"
        }
        config.setup_config(mock_env)
        
        self.assertEqual(config.GOOGLE_CLIENT_ID, "cf_dict_google_client_id")
        self.assertEqual(config.JWT_SECRET_KEY, "cf_dict_jwt_secret_key")

    def test_environment_resolution(self):
        # Default is development
        config.setup_config(None)
        self.assertEqual(config.ENVIRONMENT, "development")

        # Can be set via os.environ
        os.environ["ENVIRONMENT"] = "production"
        config.setup_config(None)
        self.assertEqual(config.ENVIRONMENT, "production")

        # Can be overridden by env object
        class MockEnv:
            def __init__(self):
                self.ENVIRONMENT = "staging"
        config.setup_config(MockEnv())
        self.assertEqual(config.ENVIRONMENT, "staging")

if __name__ == '__main__':
    unittest.main()
