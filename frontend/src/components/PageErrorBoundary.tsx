import React from 'react';
import { Alert, Button, Space } from 'antd';

interface PageErrorBoundaryProps {
  children: React.ReactNode;
  pageName?: string;
}

interface PageErrorBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

export default class PageErrorBoundary extends React.Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  constructor(props: PageErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      errorMessage: '',
    };
  }

  static getDerivedStateFromError(error: Error): PageErrorBoundaryState {
    return {
      hasError: true,
      errorMessage: error?.message || '页面渲染发生未知错误',
    };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`[${this.props.pageName || '页面'}] 渲染错误:`, error, errorInfo);
  }

  handleRetry = () => {
    this.setState({
      hasError: false,
      errorMessage: '',
    });
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          showIcon
          message={`${this.props.pageName || '页面'}加载失败`}
          description={
            <Space direction="vertical" size={12}>
              <span>{this.state.errorMessage}</span>
              <Button onClick={this.handleRetry}>重试加载</Button>
            </Space>
          }
        />
      </div>
    );
  }
}
