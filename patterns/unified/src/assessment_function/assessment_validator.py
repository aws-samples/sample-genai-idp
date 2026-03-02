import json
import logging
from typing import Optional
from idp_common.config import AssessmentConfig
from idp_common.utils import normalize_boolean_value

logger = logging.getLogger(__name__)

class AssessmentValidator:
    def __init__(self, extraction_data, assessment_config: Optional[ AssessmentConfig ]=None, enable_missing_check=False, enable_count_check=False):
        self.extraction_data = extraction_data
        self.inference_result = extraction_data.get('inference_result', {})
        self.explainability_info = extraction_data.get('explainability_info', [])
        self.assessment_config = assessment_config or AssessmentConfig() 
        self.enable_missing_check = enable_missing_check
        self.enable_count_check = enable_count_check
        
    def check_missing_explainability(self):
        """Check if all extracted attributes have assessment results"""
        if not self.explainability_info:
            return {
                'is_valid': False,
                'failed_attributes': list(self.inference_result.keys()),
                'error_message': 'No assessment results found'
            }
            
        assessments = self.explainability_info[0]
        expected_attributes = set(self.inference_result.keys())
        assessed_attributes = set(assessments.keys())
        missing_attributes = list(expected_attributes - assessed_attributes)
        if missing_attributes:
            logger.error(f"Missing from assessment: {missing_attributes}")
            # Create user-friendly error message
            if len(missing_attributes) == 1:
                user_message = f"Assessment was not completed for the '{missing_attributes[0]}' attribute. "
            else:
                attr_list = "', '".join(missing_attributes)
                user_message = f"Assessment was not completed for {len(missing_attributes)} attributes: '{attr_list}'. "
            
            return {
                'is_valid': False,
                'failed_attributes': missing_attributes,
                'error_message': user_message
            }
        return {
            'is_valid': True,
            'failed_attributes': [],
            'error_message': None
        }
    
    def check_explainability_count(self):
        """Check if all extracted items have corresponding assessment results"""
        if not self.explainability_info:
            return {
                'is_valid': True,  # Already handled by missing explainability check
                'failed_attributes': [],
                'error_message': None
            }
            
        assessments = self.explainability_info[0]
        failed_attributes = []
        
        # Check count equality for list attributes
        total_inference_items = 0
        total_assessed_items = 0
        incomplete_sections = []
        
        for attr_name in self.inference_result:
            if attr_name in assessments:
                inference_attr = self.inference_result[attr_name]
                assessment_attr = assessments[attr_name]
                
                if isinstance(inference_attr, list) and isinstance(assessment_attr, list):
                    inference_count = len(inference_attr)
                    assessment_count = len(assessment_attr)
                    
                    total_inference_items += inference_count
                    total_assessed_items += assessment_count
                    
                    if inference_count != assessment_count:
                        missing_count = inference_count - assessment_count
                        incomplete_sections.append(f"{attr_name}: {missing_count} items not assessed")
                        failed_attributes.append(
                            f"{attr_name} (Incomplete: {assessment_count}/{inference_count} items assessed)"
                        )
                        logger.warning(
                            f"Incomplete assessment for '{attr_name}': only {assessment_count} "
                            f"out of {inference_count} items were assessed"
                        )
        
        if failed_attributes:
            # Create user-friendly error message
            user_message = (
                f"Assessment was not completed for all attributes. "
                f"Total {total_inference_items} items were extracted, but only {total_assessed_items} were assessed."
            )
            return {
                'is_valid': False,
                'failed_attributes': failed_attributes,
                'error_message': user_message
            }
            
        return {
            'is_valid': True,
            'failed_attributes': [],
            'error_message': None
        }
    
    def check_explainability_exists(self):
        """Check if explainability_info has at least one element when expected attributes exist"""
        expected_attributes = set(self.inference_result.keys())
        logger.info(f"Check Explainability Exists: {self.assessment_config.enabled}")
        if (self.assessment_config.enabled and
                expected_attributes and
                (not self.explainability_info or not self.explainability_info[0])):
            return {
                'is_valid': False,
                'failed_attributes': list(expected_attributes),
                'error_message': 'No assessment information found for the extracted attributes.'
            }

        return {
            'is_valid': True,
            'failed_attributes': [],
            'error_message': None
        }

    def validate_all(self):
        """Run all validations and return comprehensive results"""
        validation_results = {
            'is_valid': True,
            'failed_attributes': [],
            'validation_errors': []
        }

        # Check missing explainability if enabled
        if self.enable_missing_check:
            missing_result = self.check_missing_explainability()
            if not missing_result['is_valid']:
                validation_results['is_valid'] = False
                validation_results['failed_attributes'].extend(missing_result['failed_attributes'])
                validation_results['validation_errors'].append(missing_result['error_message'])
        else:
            logger.debug("Skipping missing explainability check is disabled.")

        # Check count if enabled
        if self.enable_count_check:
            count_result = self.check_explainability_count()
            if not count_result['is_valid']:
                validation_results['is_valid'] = False
                validation_results['failed_attributes'].extend(count_result['failed_attributes'])
                validation_results['validation_errors'].append(count_result['error_message'])
        else:
            logger.debug("Skipping explainability count check disabled.")
        
        # Check explainability exists
        exists_result = self.check_explainability_exists()
        if not exists_result['is_valid']:
            validation_results['is_valid'] = False
            validation_results['failed_attributes'].extend(exists_result['failed_attributes'])
            validation_results['validation_errors'].append(exists_result['error_message'])
        
        # Log final validation result
        if validation_results['is_valid']:
            logger.info("Assessment validation: all or some attributes have confidence scores")
        else:
            logger.info(f"Assessment validation: {len(validation_results['failed_attributes'])} issues found")
        
        return validation_results

class AssessmentFileValidator:
    def __init__(self, json_file, enable_missing_check=False, enable_count_check=False, assessment_config=None):
        self.json_file = json_file
        self.enable_missing_check = enable_missing_check
        self.enable_count_check = enable_count_check
        self.assessment_config = assessment_config
    
    def load_and_validate(self):
        with open(self.json_file, 'r') as f:
            data = json.load(f)
        
        validator = AssessmentValidator(data, self.enable_missing_check, self.enable_count_check, self.assessment_config)
        return validator.validate_all()
