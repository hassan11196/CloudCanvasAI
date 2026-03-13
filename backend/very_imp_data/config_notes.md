# Configuration Notes

## Environment Variables

```
CLAUDE_API_KEY=sk-ant-xxxxx
DATABASE_URL=postgresql://localhost:5432/zephior
REDIS_URL=redis://localhost:6379
```

## Default Settings

- Max file size: 10MB
- Session timeout: 30 minutes
- Rate limit: 100 requests/minute

## Security Considerations

1. Always use HTTPS in production
2. Rotate API keys quarterly
3. Enable audit logging
4. Implement IP allowlisting for admin endpoints

## Backup Schedule

- Database: Daily at 2:00 AM UTC
- Files: Weekly on Sundays
- Logs: Retained for 90 days
