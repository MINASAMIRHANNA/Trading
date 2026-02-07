import { api } from "./client";

export async function runDoctor() {
  const { data } = await api.post("/doctor/run");
  return data;
}

export async function fetchDoctorChecks(runTests: boolean = true) {
  const { data } = await api.get("/doctor/checks", { params: { run_tests: runTests } });
  return data;
}

export async function fetchDoctorStatus() {
  const [stack, pipeline, dbWiring] = await Promise.all([
    api.get("/stack/health"),
    api.get("/pipeline/status", { params: { role: "all" } }),
    api.get("/system/db_wiring"),
  ]);
  return {
    stack: stack.data,
    pipeline: pipeline.data,
    dbWiring: dbWiring.data,
  };
}

export async function clearRestartFlags(role: "all" | "paper" | "live" | "pump" = "all") {
  const { data } = await api.post("/doctor/fix/clear_restart", { role });
  return data;
}

export async function clearOldCommands(role: "all" | "paper" | "live" | "pump" = "all", ageMin: number = 30) {
  const { data } = await api.post("/doctor/fix/clear_commands", { role, age_min: ageMin });
  return data;
}

export async function fetchDoctorIncidents(limit: number = 50) {
  const { data } = await api.get("/doctor/incidents", { params: { limit } });
  return data;
}
