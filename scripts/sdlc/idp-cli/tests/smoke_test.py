import os
from datetime import datetime
from idp_cli.service.install_service import InstallService
from idp_cli.service.smoketest_service import SmokeTestService
from idp_cli.service.uninstall_service import UninstallService
import pytest
from loguru import logger
from dotenv import load_dotenv
load_dotenv()
# Global variable to store resources created in setup
test_resources = None

@pytest.fixture(scope="session", autouse=True)
def setup_and_teardown():
    """
    This fixture runs once before all tests start and tears down after all tests finish.
    The 'scope="session"' parameter ensures it runs once per test session.
    The 'autouse=True' parameter ensures it runs automatically without being explicitly referenced.
    """
    # Setup phase - runs before any tests
    global test_resources
    logger.debug("\n----- Setting up test resources -----")
    cfn_prefix = f"idp-{datetime.now().strftime("%Y%m%d-%H%M%S")}"
    stack_name = f"idp-Stack-{datetime.now().strftime("%Y%m%d-%H%M%S")}" # os.getenv("IDP_STACK_NAME")
    cwd="../../../"
    install_service = InstallService(account_id=os.getenv("IDP_ACCOUNT_ID"), cfn_prefix=cfn_prefix, cwd=cwd, debug=True)

    idp_pattern = "Pattern2 - Packet processing with Textract and Bedrock"
    # TODO: This is not working, fix at a future date...
    install_service.install(admin_email=os.getenv("IDP_ADMIN_EMAIL"), idp_pattern=idp_pattern)

    install_service.publish()

    test_resources = {"stack_name": stack_name }
    
    # This yield statement separates setup from teardown
    yield
    
    # Teardown phase - runs after all tests complete
    logger.debug("\n----- Cleaning up test resources -----")
    uninstall_service = UninstallService(stack_name=stack_name, account_id=os.getenv("IDP_ACCOUNT_ID", stack_name=stack_name), cfn_prefix=cfn_prefix)

    uninstall_service.uninstall()
    test_resources = None


# Example test functions
def test_pattern2_smoketest():
    assert test_resources is not None
    assert "stack_name" in test_resources
    logger.debug("Running pattern2_smoketest")
    service = SmokeTestService(
        stack_name=test_resources["stack_name"],
        file_path="../../../../samples/rvl_cdip_package.pdf",
        verify_string="WESTERN DARK FIRED TOBACCO GROWERS"
    )
    
    result = service.do_smoketest()
    assert(result)
