// ==========================================
// ⚡ GOOGLE APPS SCRIPT BACKEND FOR MIVA BOT
// ==========================================

/**
 * 🟢 GET REQUESTS (Handles Interactive, Monthly, and Daemon Reminders)
 */
function doGet(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var action = e.parameter.action || "reminders";
    var now = new Date();
    var calendar = CalendarApp.getDefaultCalendar();

    // ==========================================
    // 🚦 ROUTE: AUTOMATED REMINDER DAEMON POLL (FAST - flipped logic)
    // ==========================================
    if (action === "reminders") {
      var reminders = [];
      
      // 1. Fetch calendar events for the next 25 hours
      var future25h = new Date(now.getTime() + (25 * 60 * 60 * 1000));
      var calEvents = calendar.getEvents(now, future25h);

      if (calEvents.length === 0) {
        return ContentService.createTextOutput(JSON.stringify({ reminders: [] })).setMimeType(ContentService.MimeType.JSON);
      }

      // 2. Filter ONLY events that land inside one of the 3 reminder windows
      var activeEvents = [];
      calEvents.forEach(function(ev) {
        var diffMs = ev.getStartTime().getTime() - now.getTime();
        var diffMins = Math.floor(diffMs / (1000 * 60));
        var tier = null;

        // 24_HOURS Tier (23h 45m to 24h 15m)
        if (diffMins >= 1425 && diffMins <= 1455) {
          tier = "24_HOURS";
        }
        // 4_HOURS Tier (3h 45m to 4h 15m)
        else if (diffMins >= 225 && diffMins <= 255) {
          tier = "4_HOURS";
        }
        // 10_MINUTES Tier (5m to 15m)
        else if (diffMins >= 5 && diffMins <= 15) {
          tier = "10_MINUTES";
        }

        if (tier) {
          activeEvents.push({
            event: ev,
            tier: tier,
            text: (ev.getTitle() + " " + ev.getLocation() + " " + ev.getDescription()).toLowerCase().replace(/[^a-z0-9]/g, '')
          });
        }
      });

      // 3. FAST EXIT: If no classes are due for a reminder right now, stop immediately!
      if (activeEvents.length === 0) {
        return ContentService.createTextOutput(JSON.stringify({ reminders: [] })).setMimeType(ContentService.MimeType.JSON);
      }

      // 4. ONLY read sheet profiles if an active event exists
      var profiles = getAllProfiles(ss);

      profiles.forEach(function(p) {
        if (!p.courses || p.courses.length === 0) return;
        var normalizedCourses = p.courses.map(function(c) { return String(c).toLowerCase().replace(/[^a-z0-9]/g, ''); });

        activeEvents.forEach(function(item) {
          var matchesCourse = normalizedCourses.some(function(codeNorm) { return codeNorm && item.text.includes(codeNorm); });
          
          if (matchesCourse) {
            var ev = item.event;
            reminders.push({
              id: (p.phone || "user") + "_" + ev.getTitle() + "_" + ev.getStartTime().getTime() + "_" + item.tier,
              phone: p.phone,
              name: p.name,
              course_code: ev.getTitle(),
              lecture_day: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "EEEE, MMMM dd"),
              lecture_time: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "hh:mm a"),
              room_link: extractMeetingLink(ev, p.live_lesson_link),
              tier: item.tier,
              ops_manager: p.operations_manager,
              ops_email: p.operations_manager_email
            });
          }
        });
      });

      return ContentService.createTextOutput(JSON.stringify({ reminders: reminders })).setMimeType(ContentService.MimeType.JSON);
    }

    // ==========================================
    // 🚦 ROUTE: INTERACTIVE WAHA BOT LOOKUP (FIXED: Meet links + full-day range)
    // ==========================================
    if (action === "interactive") {
      var profile = getProfile(ss, e.parameter.phone, e.parameter.name);
      var events = [];
      var courses = (profile && profile.courses) || [];
      
      if (profile && courses.length > 0) {
        // Query from start of today to 7 days ahead so today's classes never vanish
        var startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
        var endWindow = new Date(now.getTime() + (7 * 24 * 60 * 60 * 1000));
        var calEvents = calendar.getEvents(startOfToday, endWindow);
        var normalizedCourses = courses.map(function(c) { return String(c).toLowerCase().replace(/[^a-z0-9]/g, ''); });
        
        // Build a lookup: course code → per-row link from the sheet
        var courseLinkMap = {};
        if (profile.courses_with_links) {
          profile.courses_with_links.forEach(function(cwl) { courseLinkMap[cwl.code] = cwl.link; });
        }
        
        calEvents.forEach(function(ev) {
          var text = (ev.getTitle() + " " + ev.getLocation() + " " + ev.getDescription()).toLowerCase().replace(/[^a-z0-9]/g, '');
          for (var ci = 0; ci < normalizedCourses.length; ci++) {
            var codeNorm = normalizedCourses[ci];
            if (codeNorm && text.includes(codeNorm)) {
              var matchedCourse = profile.courses[ci];
              var perCourseLink = courseLinkMap[matchedCourse] || profile.live_lesson_link;
              events.push({
                course_code_calendar: ev.getTitle(),
                lecture_day: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "EEEE, MMMM dd, yyyy"),
                lecture_time: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "hh:mm a"),
                room_link: extractMeetingLink(ev, perCourseLink)
              });
              break;
            }
          }
        });
      }
      return ContentService.createTextOutput(JSON.stringify({ profile: profile, calendar_events: events })).setMimeType(ContentService.MimeType.JSON);
    }

    // ==========================================
    // 🚦 ROUTE: MONTHLY SCHEDULE LOOKUP
    // ==========================================
    if (action === "monthly") {
      var profileMonth = getProfile(ss, e.parameter.phone, e.parameter.name);
      var mEvents = [];
      var monthCourses = (profileMonth && profileMonth.courses) || [];
      
      if (profileMonth && monthCourses.length > 0) {
        var startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        var endOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59, 59);
        var monthlyCalEvents = calendar.getEvents(startOfMonth, endOfMonth);

        monthlyCalEvents.forEach(function(ev) {
          var text = (ev.getTitle() + " " + ev.getLocation() + " " + ev.getDescription()).toLowerCase().replace(/[^a-z0-9]/g, '');
          for (var ci = 0; ci < monthCourses.length; ci++) {
            var codeNorm = String(monthCourses[ci]).toLowerCase().replace(/[^a-z0-9]/g, '');
            if (codeNorm && text.includes(codeNorm)) {
              mEvents.push({
                course_code: ev.getTitle(),
                lecture_day: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "EEEE, dd MMMM"),
                lecture_time: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "hh:mm a"),
                lecture_end_time: Utilities.formatDate(ev.getEndTime(), "Africa/Lagos", "hh:mm a"),
                room_link: extractMeetingLink(ev, profileMonth.live_lesson_link)
              });
              break;
            }
          }
        });
      }
      
      return ContentService.createTextOutput(JSON.stringify({ 
        profile: profileMonth, 
        monthly_events: mEvents, 
        events: mEvents,
        calendar_events: mEvents
      })).setMimeType(ContentService.MimeType.JSON);
    }

    return ContentService.createTextOutput(JSON.stringify({ status: "ready" })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ error: err.toString() })).setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * 🔵 POST REQUESTS (Handles the new Python Bot integration: FAQs & Today's classes)
 */
function doPost(e) {
  try {
    var contents = {};
    if (e && e.postData && e.postData.contents) {
      contents = JSON.parse(e.postData.contents);
    }

    var action = contents.action || "";

    // ==========================================
    // 🚦 ROUTE: ESCALATION (lecturer unavailable/sick)
    // ==========================================
    if (action === "escalate") {
      var senderPhone = contents.sender_phone || "";
      var senderName = contents.sender_name || "";
      var queryText = contents.query_text || "";
      var issueType = contents.issue_type || "General Inquiry / Request";

      var ss = SpreadsheetApp.getActiveSpreadsheet();
      var profile = getProfile(ss, senderPhone, senderName);
      sendEmailEscalation(profile, queryText, issueType, senderPhone);

      return ContentService
        .createTextOutput(JSON.stringify({ status: "escalated_successfully" }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    var senderPhone = contents.sender_phone || "";
    var senderName = contents.sender_name || "";
    var queryText = contents.query_text || "";

    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // 1. Fetch Profile
    var profile = getProfile(ss, senderPhone, senderName);

    // 2. Fetch Today's Calendar Schedule (multi-course, per-row links)
    var schedule = [];
    if (profile && profile.courses && profile.courses.length > 0) {
      var calendar = CalendarApp.getDefaultCalendar();
      var now = new Date();
      var startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
      var endOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
      var todayEvents = calendar.getEvents(startOfDay, endOfDay);
      
      var courseLinkMap = {};
      if (profile.courses_with_links) {
        profile.courses_with_links.forEach(function(cwl) { courseLinkMap[cwl.code] = cwl.link; });
      }
      
      for (var ei = 0; ei < todayEvents.length; ei++) {
        var evt = todayEvents[ei];
        var text = (evt.getTitle() + " " + evt.getLocation() + " " + evt.getDescription()).toLowerCase();
        for (var ci = 0; ci < profile.courses.length; ci++) {
          var codeNorm = String(profile.courses[ci]).toLowerCase().replace(/[^a-z0-9]/g, '');
          if (codeNorm && text.includes(codeNorm)) {
            var matchedCourse = profile.courses[ci];
            var perCourseLink = courseLinkMap[matchedCourse] || profile.live_lesson_link;
            schedule.push({
              course_code_calendar: evt.getTitle(),
              lecture_day: Utilities.formatDate(evt.getStartTime(), "Africa/Lagos", "EEEE, MMMM dd"),
              lecture_time: Utilities.formatDate(evt.getStartTime(), "Africa/Lagos", "hh:mm a"),
              room_link: extractMeetingLink(evt, perCourseLink)
            });
            break;
          }
        }
      }
    }

    // 3. Fetch FAQs
    var faqs = getFaqsFromSheet(ss);

    var responsePayload = {
      profile: profile,
      schedule: schedule,
      faqs: faqs
    };

    return ContentService
      .createTextOutput(JSON.stringify(responsePayload))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ error: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}


// ==========================================
// 🛠️ SHARED HELPER FUNCTIONS
// ==========================================

/**
 * Extracts Google Meet link from Calendar Event with fallback to profile link.
 * Checks: hangout link → description regex → location → sheet fallback.
 */
function extractMeetingLink(ev, fallbackLink) {
  // 1. Native Google Calendar Meet link property
  try {
    var hangout = ev.getHangoutLink();
    if (hangout && hangout.length > 5) return hangout;
  } catch (err) {}

  // 2. Check Description for meet.google.com link
  var desc = ev.getDescription() || "";
  var meetMatch = desc.match(/https?:\/\/meet\.google\.com\/[a-z0-9\-]+/i);
  if (meetMatch) return meetMatch[0];

  // 3. Location field check
  var loc = ev.getLocation() || "";
  if (loc.toLowerCase().includes("http")) return loc;

  // 4. Fallback to Mapping Sheet default link
  return fallbackLink || "Check MIVA Portal";
}

/**
 * Finds ALL rows matching a lecturer and aggregates all assigned courses.
 * Returns raw JSON with a `courses` array (e.g. ["SEN 301", "ECO 310"]).
 */
function getProfile(ss, searchPhone, searchName) {
  var sheet = ss.getSheetByName("Mapping Sheet");
  if (!sheet) return null;

  var data = sheet.getDataRange().getValues();
  if (data.length <= 1) return null;

  var rawHeaders = data[0].map(h => String(h).trim());
  var headers = rawHeaders.map(h => h.toLowerCase().replace(/[^a-z0-9]+/g, '_'));

  var phoneIdx = headers.indexOf('phone') !== -1 ? headers.indexOf('phone') : headers.indexOf('phone_number');
  var nameIdx = headers.indexOf('name') !== -1 ? headers.indexOf('name') : headers.indexOf('student_name');
  var emailIdx = headers.indexOf('email') !== -1 ? headers.indexOf('email') : headers.indexOf('email_address');
  var courseIdx = headers.indexOf('course_code') !== -1 ? headers.indexOf('course_code') : headers.indexOf('course');

  // Live Lesson Link Detection
  var linkIdx = headers.indexOf('live_lesson_link');
  if (linkIdx === -1) {
    for (var k = 0; k < rawHeaders.length; k++) {
      var cleanH = rawHeaders[k].toLowerCase();
      if (cleanH.includes('live') && cleanH.includes('link')) {
        linkIdx = k;
        break;
      }
    }
  }

  var opsManagerIdx = headers.indexOf('operations_manager');
  var opsEmailIdx = headers.indexOf('operations_manager_email');

  var sPhone = searchPhone ? String(searchPhone).replace(/\D/g, '') : "";
  var sName = searchName ? String(searchName).toLowerCase().trim() : "";

  var matchedProfile = null;
  var allCourseCodes = [];
  var coursesWithLinks = [];

  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var phoneMatch = false;

    if (sPhone) {
      for (var j = 0; j < row.length; j++) {
        var cellData = String(row[j]).replace(/\D/g, '');
        if (cellData.length > 8 && (sPhone === cellData || sPhone.endsWith(cellData) || cellData.endsWith(sPhone))) {
          phoneMatch = true;
          break;
        }
      }
    }

    var rowName = nameIdx !== -1 ? String(row[nameIdx]).toLowerCase().trim() : "";
    var nameMatch = sName && rowName && rowName.includes(sName);

    if (phoneMatch || nameMatch) {
      // First match — capture profile fields
      if (!matchedProfile) {
        matchedProfile = {
          name: nameIdx !== -1 ? row[nameIdx] : "Student",
          phone: searchPhone,
          email: emailIdx !== -1 ? row[emailIdx] : "",
          live_lesson_link: linkIdx !== -1 ? row[linkIdx] : "",
          operations_manager: opsManagerIdx !== -1 ? row[opsManagerIdx] : "Operations Manager",
          operations_manager_email: opsEmailIdx !== -1 ? row[opsEmailIdx] : "",
        };
      }

      // Collect course code with its per-row meeting link
      var rawCourse = courseIdx !== -1 ? String(row[courseIdx] || "").trim() : "";
      var rowLink = linkIdx !== -1 ? String(row[linkIdx] || "").trim() : "";
      if (rawCourse) {
        var parts = rawCourse.split(/[,;]/);
        for (var p = 0; p < parts.length; p++) {
          var code = parts[p].trim();
          if (code && allCourseCodes.indexOf(code) === -1) {
            allCourseCodes.push(code);
            coursesWithLinks.push({ code: code, link: rowLink || "" });
          }
        }
      }
    }
  }

  if (!matchedProfile) return null;

  matchedProfile.courses = allCourseCodes;
  matchedProfile.courses_with_links = coursesWithLinks;
  matchedProfile.course_code = allCourseCodes.length > 0 ? allCourseCodes[0] : "";
  matchedProfile.all_course_codes = allCourseCodes;
  return matchedProfile;
}

/**
 * Reads questions and answers from the "FAQ" sheet tab.
 */
function getFaqsFromSheet(ss) {
  try {
    var faqSheet = ss.getSheetByName("FAQ");
    if (!faqSheet) return [];
    
    var data = faqSheet.getDataRange().getValues();
    if (data.length <= 1) return [];
    
    var faqs = [];
    for (var i = 1; i < data.length; i++) {
      var question = String(data[i][0] || "").trim();
      var answer = String(data[i][1] || "").trim();
      
      if (question && answer) {
        faqs.push({ q: question, a: answer });
      }
    }
    return faqs;
  } catch (err) {
    Logger.log("Error reading FAQ tab: " + err);
    return [];
  }
}

/**
 * Searches Google Calendar for today's scheduled classes matching the lecturer's course code.
 */
function fetchTodaySchedule(calendar, profile) {
  if (!profile || !profile.course_code) return [];
  try {
    var now = new Date();
    var startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
    var endOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);

    var events = calendar.getEvents(startOfDay, endOfDay);
    var schedule = [];

    var codeNorm = String(profile.course_code).toLowerCase().replace(/[^a-z0-9]/g, '');

    for (var i = 0; i < events.length; i++) {
      var evt = events[i];
      var text = (evt.getTitle() + " " + evt.getLocation() + " " + evt.getDescription()).toLowerCase();

      if (text.includes(codeNorm)) {
        schedule.push({
          course_code_calendar: evt.getTitle(),
          lecture_day: Utilities.formatDate(evt.getStartTime(), "Africa/Lagos", "EEEE, MMMM dd"),
          lecture_time: Utilities.formatDate(evt.getStartTime(), "Africa/Lagos", "hh:mm a"),
          room_link: evt.getLocation() || profile.live_lesson_link || "Check Portal"
        });
      }
    }
    return schedule;
  } catch (e) {
    Logger.log("Calendar lookup warning: " + e);
    return [];
  }
}

/**
 * 📧 HELPER: Sends formatted HTML escalation emails via GmailApp
 */
function sendEmailEscalation(profile, userMessage, issueType, rawPhone) {
  var recipient = (profile && profile.operations_manager_email) 
    ? profile.operations_manager_email 
    : "support@miva.edu.ng";

  var name = profile ? profile.name : "Unknown User";
  var courses = (profile && profile.courses && profile.courses.length > 0) 
    ? profile.courses.join(", ") 
    : "None / Unmapped";

  var subject = "🚨 URGENT ESCALATION: " + issueType + " - " + name;

  var htmlBody = `
    <div style="font-family: Arial, sans-serif; max-width: 600px; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px;">
      <h2 style="color: #d9534f; margin-top: 0;">⚠️ Urgent Escalation Notice</h2>
      <p style="color: #555;">An issue requiring staff follow-up was flagged by the MIVA WhatsApp Bot.</p>
      
      <hr style="border: 0; border-top: 1px solid #eee; margin: 15px 0;">
      
      <p><strong>User Name:</strong> ${name}</p>
      <p><strong>Phone Number:</strong> ${rawPhone}</p>
      <p><strong>Assigned Courses:</strong> ${courses}</p>
      <p><strong>Issue Category:</strong> ${issueType}</p>
      
      <hr style="border: 0; border-top: 1px solid #eee; margin: 15px 0;">
      
      <p><strong>User's Message:</strong></p>
      <blockquote style="background: #f9f9f9; border-left: 4px solid #d9534f; margin: 0; padding: 10px 15px; font-style: italic; color: #333;">
        "${userMessage}"
      </blockquote>
      
      <hr style="border: 0; border-top: 1px solid #eee; margin: 15px 0;">
      
      <p style="font-size: 12px; color: #888;">
        This email was sent automatically from the <strong>livelesson</strong> Workspace account via Google Apps Script. Please contact the user directly on WhatsApp or email to resolve the issue.
      </p>
    </div>
  `;

  GmailApp.sendEmail(recipient, subject, "Urgent escalation from MIVA WhatsApp Bot.", {
    htmlBody: htmlBody,
    name: "MIVA Bot Escalation System"
  });
}

/**
 * Loads ALL distinct lecturer profiles from the Mapping Sheet.
 * Used by the reminder daemon to scan everyone's calendar at once.
 */
function getAllProfiles(ss) {
  var sheet = ss.getSheetByName("Mapping Sheet");
  if (!sheet) return [];

  var data = sheet.getDataRange().getValues();
  if (data.length <= 1) return [];

  var rawHeaders = data[0].map(function(h) { return String(h).trim(); });
  var headers = rawHeaders.map(function(h) { return h.toLowerCase().replace(/[^a-z0-9]+/g, '_'); });

  var phoneIdx = headers.indexOf('phone') !== -1 ? headers.indexOf('phone') : headers.indexOf('phone_number');
  var nameIdx = headers.indexOf('name') !== -1 ? headers.indexOf('name') : headers.indexOf('student_name');
  var courseIdx = headers.indexOf('course_code') !== -1 ? headers.indexOf('course_code') : headers.indexOf('course');
  
  var linkIdx = headers.indexOf('live_lesson_link');
  if (linkIdx === -1) {
    for (var k = 0; k < rawHeaders.length; k++) {
      if (rawHeaders[k].toLowerCase().includes('live') && rawHeaders[k].toLowerCase().includes('link')) {
        linkIdx = k;
        break;
      }
    }
  }

  var profilesByPhone = {};

  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var rawPhone = phoneIdx !== -1 ? String(row[phoneIdx]).replace(/\D/g, '') : "";
    if (!rawPhone) continue;

    if (!profilesByPhone[rawPhone]) {
      profilesByPhone[rawPhone] = {
        name: nameIdx !== -1 ? row[nameIdx] : "User",
        phone: rawPhone,
        courses: [],
        live_lesson_link: linkIdx !== -1 ? row[linkIdx] : "",
        operations_manager: headers.indexOf('operations_manager') !== -1 ? row[headers.indexOf('operations_manager')] : "Operations Manager",
        operations_manager_email: headers.indexOf('operations_manager_email') !== -1 ? row[headers.indexOf('operations_manager_email')] : ""
      };
    }

    if (courseIdx !== -1 && row[courseIdx]) {
      var splitCodes = String(row[courseIdx]).split(/[,;\/]+/);
      splitCodes.forEach(function(code) {
        var trimmed = code.trim();
        if (trimmed && profilesByPhone[rawPhone].courses.indexOf(trimmed) === -1) {
          profilesByPhone[rawPhone].courses.push(trimmed);
        }
      });
    }
  }

  var result = [];
  for (var key in profilesByPhone) {
    result.push(profilesByPhone[key]);
  }
  return result;
}