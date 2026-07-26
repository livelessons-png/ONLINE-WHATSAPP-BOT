// ==========================================
// ⚡ GOOGLE APPS SCRIPT BACKEND FOR MIVA BOT
// ==========================================

/**
 * 🟢 GET REQUESTS (Handles your existing Interactive & Monthly schedule checks)
 */
function doGet(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var action = e.parameter.action || "reminders";
    var now = new Date();
    var calendar = CalendarApp.getDefaultCalendar();

    // ==========================================
    // 🚦 ROUTE: INTERACTIVE WAHA BOT LOOKUP
    // ==========================================
    if (action === "interactive") {
      var profile = getProfile(ss, e.parameter.phone, e.parameter.name);
      var events = [];
      
      if (profile && profile.course_code) {
        var future = new Date(now.getTime() + (24 * 60 * 60 * 1000));
        var calEvents = calendar.getEvents(now, future);
        
        calEvents.forEach(ev => {
          var text = (ev.getTitle() + " " + ev.getLocation() + " " + ev.getDescription()).toLowerCase();
          var codeNorm = String(profile.course_code).toLowerCase().replace(/[^a-z0-9]/g, '');
          
          if (text.includes(codeNorm)) {
            events.push({
              course_code_calendar: ev.getTitle(),
              lecture_day: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "EEEE, MMMM dd"),
              lecture_time: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "hh:mm a"),
              room_link: ev.getLocation() || profile.live_lesson_link || "No Link Provided"
            });
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
      
      if (profileMonth && profileMonth.course_code) {
        var startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        var endOfMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59, 59);
        var monthlyCalEvents = calendar.getEvents(startOfMonth, endOfMonth);
        
        var codeNorm = String(profileMonth.course_code).toLowerCase().replace(/[^a-z0-9]/g, '');

        monthlyCalEvents.forEach(ev => {
          var text = (ev.getTitle() + " " + ev.getLocation() + " " + ev.getDescription()).toLowerCase().replace(/[^a-z0-9]/g, '');
          
          if (text.includes(codeNorm)) {
            mEvents.push({
              course_code: ev.getTitle(),
              lecture_day: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "EEEE, dd MMMM"),
              lecture_time: Utilities.formatDate(ev.getStartTime(), "Africa/Lagos", "hh:mm a"),
              lecture_end_time: Utilities.formatDate(ev.getEndTime(), "Africa/Lagos", "hh:mm a"),
              room_link: ev.getLocation() || profileMonth.live_lesson_link || "No Link Provided"
            });
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

    var senderPhone = contents.sender_phone || "";
    var senderName = contents.sender_name || "";
    var queryText = contents.query_text || "";

    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // 1. Fetch Profile
    var profile = getProfile(ss, senderPhone, senderName);

    // 2. Fetch Today's Calendar Schedule
    var calendar = CalendarApp.getDefaultCalendar();
    var schedule = fetchTodaySchedule(calendar, profile);

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
 * Unified function to find a profile in the "Mapping Sheet"
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

  var sPhone = searchPhone ? String(searchPhone).replace(/\D/g, '') : "";
  var sName = searchName ? String(searchName).toLowerCase().trim() : "";

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
      var lessonLink = linkIdx !== -1 ? row[linkIdx] : "";
      
      return {
        name: nameIdx !== -1 ? row[nameIdx] : "Student",
        phone: searchPhone, 
        email: emailIdx !== -1 ? row[emailIdx] : "",
        course_code: courseIdx !== -1 ? row[courseIdx] : "",
        live_lesson_link: lessonLink,
        operations_manager: headers.indexOf('operations_manager') !== -1 ? row[headers.indexOf('operations_manager')] : "Operations Manager",
        operations_manager_email: headers.indexOf('operations_manager_email') !== -1 ? row[headers.indexOf('operations_manager_email')] : "",
        all_course_codes: [courseIdx !== -1 ? row[courseIdx] : ""]
      };
    }
  }
  return null;
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