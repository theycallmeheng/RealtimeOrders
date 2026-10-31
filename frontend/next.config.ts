import type { NextConfig } from "next";
import { applicationPaths } from "./lib/navigation";
const config: NextConfig = {
  async rewrites() {
    return applicationPaths.map(source => ({ source, destination: "/" }));
  },
  poweredByHeader: false,
  allowedDevOrigins: ["localhost", "127.0.0.1"],
};
export default config;
