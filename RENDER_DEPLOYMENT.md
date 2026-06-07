# Render.com Deployment Guide

## Overview
This application runs on Render.com with the following components:
- **Backend**: Flask web application (Python)
- **Database**: MongoDB Atlas (cloud MongoDB)
- **Bot**: Telegram bot integration
- **Port**: 10000

## Prerequisites
1. Render.com account
2. MongoDB Atlas cluster (free tier available)
3. Telegram bot (created via @BotFather)

## Step 1: Set Up MongoDB Atlas

1. Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a free cluster
3. Create a database user with username and password
4. Get the connection string in format:
   ```
   mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
   ```
5. Add your Render.com IP to MongoDB IP whitelist (or allow all `0.0.0.0/0`)

## Step 2: Create Render Service

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click "New +"
3. Select "Web Service"
4. Connect your GitHub repository
5. Use these settings:
   - **Name**: skladchi-bot-crm
   - **Environment**: Python 3
   - **Region**: Choose closest to users
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`

## Step 3: Configure Environment Variables

In Render dashboard, add these environment variables:

### Required Variables
```
BOT_TOKEN=your_telegram_bot_token
ADMIN_ID=your_telegram_user_id
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
SECRET_KEY=generate_a_random_string_here
WEB_APP_URL=https://your-app-name.onrender.com
```

### Optional Variables
```
FLASK_SECRET_KEY=alternative_secret_key
WEB_ADMIN_PASSWORD=admin123
FLASK_ENV=production
```

## Step 4: Deploy

1. Push code to GitHub
2. Render will automatically deploy on push
3. Monitor logs in Render dashboard

## Troubleshooting

### 500 Error on /login
**Problem**: Database connection fails
**Solutions**:
1. Verify `MONGO_URI` is set correctly
2. Check MongoDB whitelist includes Render IP
3. Check database user credentials are correct
4. View logs: `/health` endpoint shows connection status
5. Visit `/status` page for debugging info

### Database Connection Timeout
**Solutions**:
1. Application retries 3 times with 2-second delays
2. Check MongoDB cluster is running
3. Increase serverSelectionTimeoutMS if needed
4. Use connection pooling on MongoDB Atlas

### Bot Not Responding
**Problem**: Telegram bot not responding to commands
**Solutions**:
1. Verify `BOT_TOKEN` is correct
2. Verify `WEB_APP_URL` is set to your Render URL
3. Check bot commands are registered
4. View application logs for errors

## Health Check

- `GET /health` - Returns JSON with database status
- `GET /status` - Returns HTML status page with debugging info

## Logs

View application logs in Render dashboard:
1. Go to your service
2. Click "Logs" tab
3. Filter by "All Logs" or specific timeframe

## Scaling

For production use:
1. Upgrade from free tier to paid plan
2. Enable autoscaling if needed
3. Monitor CPU and memory usage
4. Consider MongoDB Atlas paid tier for better performance

## Recovery

If application crashes:
1. Render will automatically restart failed services
2. Check logs for error cause
3. Recent deployment can be rolled back
4. Contact Render support if persistent

## Performance Tips

1. **Database**: 
   - Use MongoDB Atlas M0 free tier minimum
   - Enable backups for production
   - Monitor connection pool

2. **Render**:
   - Use region closest to users
   - Monitor CPU/memory in dashboard
   - Enable health checks

3. **Application**:
   - Database calls have null checks
   - Initialize with retry logic
   - Handle graceful degradation

## Security Notes

1. **Never** commit `.env` file with real credentials
2. Use Render's environment variables
3. MongoDB credentials should be strong
4. Regularly rotate secrets
5. Enable MongoDB IP whitelist

## Monitoring Checklist

- [ ] Bot receives commands
- [ ] Web dashboard loads
- [ ] Orders can be created
- [ ] Database queries are fast
- [ ] Logs show no errors
- [ ] /health endpoint returns 200
- [ ] /login page loads
- [ ] Customer search works
- [ ] Reports display data

## Contact & Support

For Render issues: https://render.com/docs
For MongoDB issues: https://docs.mongodb.com/
For Telegram Bot API: https://core.telegram.org/bots/api
