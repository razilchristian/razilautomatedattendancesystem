const axios = require('axios');
const QRCode = require('qrcode');

// Backend API URL and teacher auth token (replace with real token)
const BACKEND_URL = 'http://localhost:5000/api/generate-qr';
const TEACHER_AUTH_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...';

// Example student details to generate QR for
const students = [
  { username: "DIP301", email: "razilchristian@gmail.com" },
  { username: "DIP302", email: "student2@example.com" }
];

// Generate and send QR code for each student
async function generateAndStoreQR(student) {
  try {
    // QR payload can be anything (here simple JSON)
    const qrPayload = JSON.stringify({
      username: student.username,
      email: student.email,
      issuedAt: new Date().toISOString()
    });

    // Generate QR code as data URL (base64 PNG)
    const qrDataUrl = await QRCode.toDataURL(qrPayload, { errorCorrectionLevel: 'H' });

    // Call backend API to save QR code
    const response = await axios.post(
      BACKEND_URL,
      {
        username: student.username,
        email: student.email,
        qr_data: qrDataUrl
      },
      {
        headers: {
          Authorization: `Bearer ${TEACHER_AUTH_TOKEN}`,
          'Content-Type': 'application/json'
        }
      }
    );

    console.log(`QR code generated and stored for ${student.username}:`, response.data.message);
  } catch (error) {
    console.error(`Failed to generate/store QR for ${student.username}:`, error.response?.data || error.message);
  }
}

// Entry point: generate QR for all students
async function main() {
  for (const student of students) {
    await generateAndStoreQR(student);
  }
}

main();
