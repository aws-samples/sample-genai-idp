# idp-accelerator-cli — reserved name placeholder

**This is not a functional package.** It contains no code and importing it
raises `RuntimeError`.

This name is reserved by Amazon Web Services for the command-line interface of the
[GenAI Intelligent Document Processing Accelerator][repo]. It is published as a
placeholder so the name cannot be registered by a third party and used to attack
builds of that project through dependency confusion.

## Looking for the real CLI?

The `idp-cli` command ships inside the accelerator repository and is installed from a
local checkout, never from PyPI:

```bash
git clone https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws
cd accelerated-intelligent-document-processing-on-aws
make setup
```

See the [repository][repo] for documentation.

## Security

If you believe you installed this package because a build resolved a bare
requirement from PyPI rather than from a local checkout, that is a
dependency-confusion symptom worth investigating. The accelerator ships a
detector at `scripts/check_first_party_deps.py`.

To report a security issue in the accelerator, follow the disclosure process in
the [repository][repo].

[repo]: https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws
