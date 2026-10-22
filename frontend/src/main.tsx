import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.js";
import "./styles.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("React 挂载节点 #root 不存在。");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
