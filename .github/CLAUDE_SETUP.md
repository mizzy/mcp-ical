# Claude Code Integration Setup Guide

This guide will help you complete the setup of Claude-powered code review and assistance workflows using the Anthropic API directly.

## 📋 Prerequisites

1. **Anthropic API Access**: You need an Anthropic API key with Claude access
2. **GitHub Repository**: Admin access to this repository
3. **GitHub Actions**: Enabled for your repository (usually enabled by default)

## ⚡ How It Works

Instead of relying on a third-party GitHub Action, these workflows use:
- **Direct Anthropic API calls** via Python script
- **Claude 3.5 Sonnet** for intelligent code analysis  
- **GitHub API integration** for posting comments and reviews
- **Custom prompts** tailored for MCP and EventKit development

## 🔑 Step 1: Set Up Anthropic API Key

### Get Your API Key
1. Visit [Anthropic Console](https://console.anthropic.com/)
2. Sign in or create an account
3. Navigate to **API Keys** section
4. Create a new API key for this project
5. Copy the API key (starts with `sk-ant-`)

### Add to GitHub Secrets
1. Go to your repository on GitHub
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `ANTHROPIC_API_KEY`
5. Value: Your Anthropic API key
6. Click **Add secret**

## 🚀 Step 2: Enable GitHub Actions

### Via GitHub Web Interface
1. Go to your repository
2. Click the **Actions** tab
3. If prompted, click **I understand my workflows, go ahead and enable them**

### Via Command Line
```bash
# Enable GitHub Actions for the repository
gh api repos/:owner/:repo --method PATCH --field has_actions=true
```

## 🔧 Step 3: Configure Workflows

The following workflows have been set up:

### 1. **Claude Code Review** (`.github/workflows/claude-code-review.yml`)
- **Triggers**: Pull requests (opened, synchronized, reopened)
- **Purpose**: Automated code review with Claude 3.5 Sonnet
- **Features**: 
  - Analyzes only changed Python/markdown files
  - MCP-specific pattern recognition
  - EventKit integration review
  - Security and performance checks
  - Posts detailed review as PR comment

### 2. **Claude Code Assistant** (`.github/workflows/claude-code-assistant.yml`)  
- **Triggers**: Issues, comments mentioning `@claude`
- **Purpose**: Interactive code assistance on-demand
- **Features**:
  - Responds to `@claude <your question>` in issues/comments
  - Code explanation and documentation help
  - Bug analysis and troubleshooting guidance
  - Feature suggestions and implementation advice
  - MCP and EventKit specific expertise

## 📝 Step 4: Customize Configuration

Edit `.github/claude-config.yml` to customize:

- **Review focus areas**: Specific aspects of code to emphasize
- **Coding standards**: Enforcement of style guides and best practices
- **Security patterns**: Calendar/reminder specific security considerations
- **Performance thresholds**: Limits for function complexity and file size

## 🎯 Step 5: Test the Setup

### Test Code Review
1. Create a new branch and make a small code change
2. Open a pull request
3. Check the **Actions** tab for the Claude review workflow
4. Review the automated feedback in PR comments

### Test Assistant
1. Create a new issue or comment on an existing one
2. Include `@claude` in your message with a question about the code
3. Wait for Claude to respond with assistance

## 💡 Usage Examples

### In Pull Request Comments
```
@claude Can you explain how the EventKit integration works in this PR?
@claude Are there any security concerns with the reminder access patterns?
@claude Suggest optimizations for the calendar query performance
```

### In Issue Descriptions
```
@claude Help troubleshoot why reminders aren't being created properly
@claude Explain the difference between EKEvent and EKReminder handling
@claude Suggest improvements for error handling in the CalendarManager
```

## 🔍 Monitoring and Maintenance

### Check Workflow Status
```bash
# View recent workflow runs
gh run list --limit 10

# View specific workflow run details
gh run view <run-id>

# View workflow logs
gh run view <run-id> --log
```

### Update API Usage
- Monitor your Anthropic API usage in the console
- Set up billing alerts if needed
- Consider rate limiting for high-volume repositories

## 🛠️ Troubleshooting

### Common Issues

1. **Missing API Key**
   - Verify `ANTHROPIC_API_KEY` secret is set correctly
   - Check the secret name matches exactly

2. **Workflow Permissions**
   - Ensure workflows have necessary permissions (already configured)
   - Check repository settings allow Actions

3. **Rate Limiting**
   - Monitor API usage limits
   - Consider adjusting workflow triggers if needed

### Getting Help

- Check the **Actions** tab for detailed error logs
- Review the Anthropic API documentation
- Examine workflow run details for specific error messages

## 🎉 Next Steps

Once set up, Claude will:
- ✅ Automatically review all pull requests
- ✅ Provide code assistance when mentioned
- ✅ Focus on MCP and EventKit specific patterns
- ✅ Suggest security and performance improvements
- ✅ Help with documentation and troubleshooting

The Claude Code Actions are now ready to enhance your development workflow!