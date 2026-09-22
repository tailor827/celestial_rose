# ==============================================================================
# PARADISO — PRODUCTION REPORT BLUEPRINT (R)
# ==============================================================================
# Fully self-contained, standalone R report script. No CLI arguments needed.
#
# To configure for your report:
#   1. Set REPORT_NAME below.
#   2. Put your dependency checks in check_dependencies().
#   3. Put your data reading, calculation, and saving logic in run_report().
# Everything else (logging receipts, error catching, queue rotation) is automated.
# ==============================================================================

# ==============================================================================
# 1. CONFIGURATION (Edit Here)
# ==============================================================================
REPORT_NAME <- "Sample_R_Report_Blueprint"

# Automatic date determination (defaults to today's date YYYYMMDD)
TODAY <- format(Sys.Date(), "%Y%m%d")


# ==============================================================================
# 2. YOUR REPORT LOGIC (Edit Here)
# ==============================================================================
check_dependencies <- function() {
  # Check if upstream files, database tables, or prerequisite reports are ready.
  # Return TRUE  -> Dependencies ready, proceed to execute report.
  # Return FALSE -> Prerequisite not ready yet; Paradiso will rotate to the back
  #                 of the queue and retry later WITHOUT penalizing retry limits.
  cat(sprintf("[%s] Checking upstream dependencies for date %s...\n", format(Sys.time(), "%H:%M:%S"), TODAY))

  # --- Example check you can adapt ---
  # upstream_file <- file.path("C:/datasets", sprintf("sales_%s.csv", TODAY))
  # return(file.exists(upstream_file))

  return(TRUE)  # Change to your real check
}


run_report <- function() {
  # Your main report workload: extract, transform, and publish deliverables.
  # Returns: A short summary message to log in Paradiso.
  cat(sprintf("[%s] Starting data processing for %s...\n", format(Sys.time(), "%H:%M:%S"), TODAY))

  # --- WRITE YOUR R DATA PROCESSING CODE HERE ---
  # Example:
  # df <- read.csv("input.csv")
  # summary_table <- aggregate(amount ~ category, data = df, sum)
  # write.csv(summary_table, sprintf("output_%s.csv", TODAY))

  total_records <- 1500
  cat(sprintf("[%s] Publishing report deliverables...\n", format(Sys.time(), "%H:%M:%S")))

  return(sprintf("Successfully processed %d records for %s.", total_records, TODAY))
}


# ==============================================================================
# 3. PARADISO AUTOMATION ENGINE (Boilerplate — Do Not Modify)
# ==============================================================================
# Pure base R (zero external packages required)
args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args_all, value = TRUE)
if (length(file_arg) > 0) {
  script_dir <- dirname(normalizePath(sub("^--file=", "", file_arg[1])))
} else {
  script_dir <- getwd()
}
workspace_dir <- dirname(script_dir)

paradiso_logs_dir <- file.path(workspace_dir, "paradiso", "logs")
if (!dir.exists(paradiso_logs_dir)) {
  dir.create(paradiso_logs_dir, recursive = TRUE, showWarnings = FALSE)
}
receipt_file <- file.path(paradiso_logs_dir, paste0(REPORT_NAME, ".json"))

write_receipt <- function(status, last_output, reason = "", duration = "--") {
  clean_str <- function(s) {
    s <- gsub("\\\\", "\\\\\\\\", s)
    s <- gsub('"', '\\\\"', s)
    s <- gsub("\r", "", s)
    s <- gsub("\n", "\\\\n", s)
    return(s)
  }
  now_str <- format(Sys.time(), "%Y-%m-%d %H:%M:%S")
  json_body <- paste0(
    "{\n",
    '  "name": "', clean_str(REPORT_NAME), '",\n',
    '  "status": "', clean_str(status), '",\n',
    '  "last_run": "', now_str, '",\n',
    '  "duration": "', clean_str(duration), '",\n',
    '  "last_output": "', clean_str(last_output), '",\n',
    '  "reason": "', clean_str(ifelse(nchar(reason) > 0, reason, last_output)), '"\n',
    "}\n"
  )
  tryCatch({
    writeLines(json_body, con = receipt_file, useBytes = TRUE)
  }, error = function(e) {
    cat(sprintf("[Warning] Failed to write receipt: %s\n", e$message), file = stderr())
  })
}

main <- function() {
  start_time <- Sys.time()
  cat("============================================================\n")
  cat(sprintf("Running: %s | Date: %s [R Runtime]\n", REPORT_NAME, TODAY))
  cat("============================================================\n")

  tryCatch({
    # Step 1: Upstream Dependency Check
    if (!check_dependencies()) {
      skip_msg <- sprintf("SKIPPED: Missing dependency for %s on %s (waiting for upstream data)", REPORT_NAME, TODAY)
      cat(sprintf("[*] %s\n", skip_msg))
      elapsed <- sprintf("%.1fs", as.numeric(difftime(Sys.time(), start_time, units = "secs")))
      write_receipt(
        status = "Retrial",
        last_output = skip_msg,
        reason = "Dependencies not yet available. Re-queued for rotation.",
        duration = elapsed
      )
      quit(save = "no", status = 0)
    }

    # Step 2: Run Report
    summary_msg <- run_report()

    # Step 3: Success Completion
    elapsed <- sprintf("%.1fs", as.numeric(difftime(Sys.time(), start_time, units = "secs")))
    full_msg <- sprintf("%s completed in %s. %s", REPORT_NAME, elapsed, summary_msg)
    cat(sprintf("[+] %s\n", full_msg))
    write_receipt(
      status = "Completed",
      last_output = full_msg,
      reason = "Execution completed successfully",
      duration = elapsed
    )
    quit(save = "no", status = 0)

  }, error = function(e) {
    # Step 4: Error Handling
    elapsed <- sprintf("%.1fs", as.numeric(difftime(Sys.time(), start_time, units = "secs")))
    err_msg <- sprintf("FAILED: Unhandled exception in %s: %s", REPORT_NAME, e$message)
    cat(sprintf("[-] %s\n", err_msg), file = stderr())
    write_receipt(
      status = "Failed",
      last_output = err_msg,
      reason = paste0("Error occurred: ", e$message),
      duration = elapsed
    )
    quit(save = "no", status = 1)
  })
}

main()
