// Security-focused ESLint configuration
// Add this configuration to help detect potential XSS vulnerabilities

module.exports = {
  "extends": [
    "react-app",
    "react-app/jest"
  ],
  "plugins": [
    "no-unsanitized"
  ],
  "rules": {
    // Prevent innerHTML usage with dynamic content
    "no-unsanitized/property": "error",
    
    // Prevent unsafe DOM methods
    "no-unsanitized/method": "error",
    
    // React specific security rules
    "react/no-danger": "warn",
    "react/no-danger-with-children": "error",
    
    // General security rules
    "no-eval": "error",
    "no-implied-eval": "error",
    "no-new-func": "error",
    "no-script-url": "error"
  }
};
