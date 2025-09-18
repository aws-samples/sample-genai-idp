#!/usr/bin/env python3
"""
Simple script to test CloudFormation template for basic structural issues
"""
import json
import sys

def check_template_structure(template_path):
    """Check for basic structural issues in CloudFormation template"""
    try:
        with open(template_path, 'r') as f:
            content = f.read()
        
        # Check for basic YAML structure issues
        issues = []
        
        # Check for unmatched brackets/braces
        open_brackets = content.count('[')
        close_brackets = content.count(']')
        if open_brackets != close_brackets:
            issues.append(f"Unmatched square brackets: {open_brackets} open, {close_brackets} close")
        
        open_braces = content.count('{')
        close_braces = content.count('}')
        if open_braces != close_braces:
            issues.append(f"Unmatched curly braces: {open_braces} open, {close_braces} close")
        
        # Check for common CloudFormation issues
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            # Check for tabs (should use spaces)
            if '\t' in line:
                issues.append(f"Line {i}: Contains tabs (should use spaces)")
            
            # Check for common reference issues
            if '!Ref' in line and 'AWS::NoValue' not in line:
                # Extract the reference
                ref_part = line.split('!Ref')[1].strip()
                if ref_part.startswith(' '):
                    ref_name = ref_part.split()[0]
                    # Check if it looks like a resource that might not exist
                    if 'OSS' in ref_name and 'Collection' in ref_name:
                        issues.append(f"Line {i}: Potential reference to conditional OpenSearch resource: {ref_name}")
        
        if issues:
            print("Potential issues found:")
            for issue in issues:
                print(f"  - {issue}")
            return False
        else:
            print("No obvious structural issues found")
            return True
            
    except Exception as e:
        print(f"Error reading template: {e}")
        return False

if __name__ == "__main__":
    template_path = sys.argv[1] if len(sys.argv) > 1 else "options/bedrockkb/template.yaml"
    success = check_template_structure(template_path)
    sys.exit(0 if success else 1)