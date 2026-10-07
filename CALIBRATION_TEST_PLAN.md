# Preliminary rover calibration plan

Status: no physical calibration measurements have been recorded. The manual controller exists; coordinate-following execution is not implemented. The timed-route draft estimates durations from operator measurements and sends no commands. Target tolerance is 5 mm, not an achieved accuracy. This is the work planned for the next testing session, not a promise that autonomous scanning will be ready next week.

## Before moving

1. Download/extract the repository and run SURE2.bat. Use Simulator first to learn the controls and calibration form under Debug > Motion calibration and preliminary route draft. Simulation accepts only software-example records. Keep simulation examples separate from physical trials.
2. For physical testing, use a clear test area outside the chamber, secure the assembled rover/load and loose cables, and keep its power cutoff accessible. Measure the actual footprint, including attachments and turning sweep. Connect the rover Wi-Fi, start Live only when ready, and verify the mode badge. Do not run a second controller or telemetry process.
3. With all wheels raised, the operator checks forward/reverse, both pivots, release, STOP and reconnect/rearm. Record the observed wheel behavior. Do not proceed to floor trials until stopping works. The software timeout cannot guarantee a stop over a broken link; verify the installed firmware's behavior with wheels raised.
4. While stopped, use Read battery + IMU. Save returned raw values and missing fields as they are. Voltage is not a calibrated battery percentage. PWM is commanded demand, not measured speed. No X/Y position is measured by this project.

## Choose a lane, not an assumed one-foot box

A foot is exactly 304.8 mm. A 304.8 mm-wide box cannot provide 304.8 mm of straight travel for a rover with nonzero length. Available center travel is the measured internal lane length minus the rover's length and clearance at both ends. The nominal bare 194 mm rover would leave only 110.8 mm of center travel in that box before adding any margins; the mounted assembly may be larger. Measure it. Do not use a tabletop edge as a boundary.

Mark a longer unobstructed lane with a tape measure, leaving room beyond the target for stopping. Begin with short distances, then test a 304.8 mm target only if the measured space allows it. Use soft visual boundary markers that cannot snag wheels or block an escape route; do not rely on collisions to stop the rover. Turning needs a separate measured swept area.

Mark the rover's reference point and a heading line. Record start/finish center positions in millimeters from one fixed origin (+X along the first lane, +Y perpendicular). Keep the mounted load, floor and battery condition consistent within a group of trials.

## Straight travel and stopping

1. Select a manually tested PWM; record the value shown by the controller. Begin with a brief operator-held command, such as the existing 0.25-second bench-test interval, if the available space and stopping behavior permit it. Release, press STOP, and wait until physically stationary. The software does not start this test for you.
2. Time the commanded interval using video or a stopwatch. Alternatively use log timestamps, explicitly marked as command timing rather than measured motor timing. Network/firmware delay is not included in a command timestamp.
3. Measure start-to-rest displacement. Record direction, commanded PWM, interval, distance, surface, assembly/load/battery condition, and measurement method under Debug > Motion calibration. If it did not move, enter zero displacement and describe the stall; do not discard failed trials.
4. If video/marking permits, also measure travel from key release to rest. Leave this field blank when unknown. Save lateral drift and final heading in notes, or use the existing manual station-trial form for measured X/Y and heading.
5. Repeat at least three times from the same reference. Use five or more if practical. Use a new condition label after changing PWM, load or surface. Repeat reverse separately if reverse travel will be used.
6. Compare spread, bias and stopping drift before trying a longer interval. Displacement divided by interval is only an effective estimate for that test; startup/coasting makes scaling to other distances unreliable. No automatic power increase or distance correction is performed.

## Turning

1. Keep the same reference point and use a marked heading line/protractor or overhead video. Run brief operator-held left pivots, STOP, then measure the total rotation magnitude in degrees and any center translation.
2. Repeat left trials at least three times. Repeat right trials separately; do not assume equal rates. Approach 90 degrees incrementally only after short trials and the turning sweep are understood. Record stalls, slipping and any wheel that stops.
3. Use the calibration form's Left/Right pivot options. Enter degrees, not millimeters, for rotation. Any release-to-rest translation remains millimeters. No IMU-derived position is used.

## Prepare the draft and test stations later

1. In the local planner, export JSON or use Settings > Use this design in controller test. In Debug, load that plan. Enter the same PWM/surface/configuration/evidence/timing-method fields used for the trials, then select Prepare timed-route draft.
2. The compiler requires at least three usable trials for each direction the route needs. It keeps failed trials visible and rejects groups containing stalls. A forward/left snake route need not invent right/reverse measurements. Software examples remain explicitly synthetic.
3. Download the draft JSON. It lists estimated drive/turn legs, the source trial IDs and any extrapolation beyond tested distances/angles. It also lists manual position/height checks. Hardware execution is disabled; downloading the file does not move the rover.
4. Mark a small set of stations and manually drive to them. Record actual X/Y, heading, approach and trial number using the existing station-trial form. Compare repeatability against the desired 5 mm tolerance before attempting more rows. Short manual trials come before any automatic sequence.
5. A future timed executor must use the controller's single writer, STOP/deadman/rearm behavior and explicit operator readiness, with bounded movements and interruptions tested in simulation first. Timing alone will still be open-loop. Reliable closed-loop X/Y needs measured position feedback, calibration to the chamber datum and a controller that corrects position error.
6. Lift homing/height feedback and the airflow probe's real data interface are separate unfinished work. Five-second preview transitions are animation assumptions. Dwell timers do not prove measurements were acquired. Do not claim a physical scan is complete.

## Save evidence after every test

The local controller automatically records timestamped commands, returned raw responses, errors, stop/reconnect events and UI events under test_runs/<session-id>/controller_log.jsonl. Observations, station trials, calibration records and the draft are saved in validation.json. Starting the controller creates a session; reconnecting its browser retains that session's evidence. Read-only hardware tools use their own records.

Press STOP, cancel/finish timers, then use Download complete session ZIP in Debug. It includes the current validation report and retained raw log plus its rotated backup. Keep a copy outside the Git repository before the next session. No automatic log is evidence of wheel motion unless supported by a physical observation/measurement.

Automatic retention is bounded: latest 10 managed sessions with a 90 MB budget, protecting active sessions. Per-session raw logs rotate at 4 MB with one backup; older events can be lost in a long run. Protected concurrent sessions or unmanaged legacy folders are not deleted to satisfy the budget. This is bounded troubleshooting history, not permanent recording of every event forever. Export important sessions; runtime files are excluded from GitHub.

Bring back the ZIP, a photo/sketch of the measured lane and assembly, and trial measurements. Do not include passwords or tokens in notes. Next session's success criteria are reliable manual stop/direction behavior, repeatable measured straight/turn trials, and a reviewed preliminary timing draft—not autonomous scanning certification.
