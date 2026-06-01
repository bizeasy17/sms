```markdown
# Top-Bottom Command Sequence

This document describes the sequence of commands for running top-bottom analysis in the `management/commands` module.

## Command Sequence

1. **Initialize Environment**
    ```bash
    python manage.py shell
    ```

2. **Run Top Analysis**
    ```bash
    python manage.py identifytb
    ```

3. **Run Bottom Analysis**
    ```bash
    python manage.py calculategl
    ```

4. **Review Results**
    ```bash
    python manage.py analyzetb


5. **Generate Report**
    ```bash
    python manage.py refinetb


## Notes

- Ensure all dependencies are installed before running the commands.
- Modify command arguments as needed for your specific use case.
```