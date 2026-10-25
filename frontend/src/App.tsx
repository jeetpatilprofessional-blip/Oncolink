import React from "react";
import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import { HealthPage } from "./pages/HealthPage";
import { DevComponentsPage } from "./pages/DevComponentsPage";

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HealthPage />} />
        {/* /dev/components route only active in development */}
        {import.meta.env.DEV ? (
          <Route path="/dev/components" element={<DevComponentsPage />} />
        ) : (
          <Route path="/dev/components" element={<Navigate to="/" replace />} />
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
