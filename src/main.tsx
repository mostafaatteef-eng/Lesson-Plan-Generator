import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';

class AppErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-[#FAF9F5] text-[#141716] flex items-center justify-center p-6">
          <div className="max-w-md w-full rounded-[14px] border border-[#E6E1D3] bg-white p-6 space-y-3">
            <h1 className="text-[16px] font-semibold">Something went wrong</h1>
            <p className="text-[13px] text-[#525B58] leading-relaxed">
              {this.state.error.message || 'An unexpected interface error occurred.'}
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="min-h-[40px] px-4 py-2 text-[13px] font-semibold rounded-[10px] bg-[#137A74] hover:bg-[#0F6661] text-white"
            >
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById('root')!).render(
  <AppErrorBoundary>
    <App />
  </AppErrorBoundary>
);
