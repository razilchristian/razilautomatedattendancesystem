const express = require('express');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const csv = require('csv-parser');
const mysql = require('mysql2/promise');
const axios = require('axios');
const jwt = require('jsonwebtoken');

const app = express();
const port = 5000;

// Secret key for JWT (in production, use env var)
const JWT_SECRET = 'sD9#feL4@yP1v7QwZ!mXe3LtR8&jKlCz';

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
const upload = multer({ storage: multer.memoryStorage() });

// MySQL connection pool
const pool = mysql.createPool({
  host: 'localhost',
  user: 'root',
  password: '',
  database: 'studentattendance',
  waitForConnections: true,
  connectionLimit: 10,
  queueLimit: 0,
});

// Setup DB tables if not exist
async function createTables() {
  const conn = await pool.getConnection();
  await conn.execute(`
    CREATE TABLE IF NOT EXISTS users (
      id INT AUTO_INCREMENT PRIMARY KEY,
      username VARCHAR(50) UNIQUE NOT NULL,
      fullname VARCHAR(100),
      email VARCHAR(100) NOT NULL,
      branch VARCHAR(50),
      classroom VARCHAR(20)
    )
  `);
  await conn.execute(`
    CREATE TABLE IF NOT EXISTS students (
      id INT AUTO_INCREMENT PRIMARY KEY,
      enrollment_no VARCHAR(30) UNIQUE,
      name VARCHAR(100),
      classroom VARCHAR(10),
      class_name VARCHAR(30),
      division VARCHAR(10)
    )
  `);
  await conn.execute(`
    CREATE TABLE IF NOT EXISTS attendance (
      id INT AUTO_INCREMENT PRIMARY KEY,
      student_id INT,
      date DATE,
      present BOOLEAN,
      FOREIGN KEY(student_id) REFERENCES students(id)
    )
  `);
  await conn.execute(`
    CREATE TABLE IF NOT EXISTS qr_codes (
      id INT AUTO_INCREMENT PRIMARY KEY,
      username VARCHAR(50) NOT NULL,
      email VARCHAR(100) NOT NULL,
      qr_data TEXT,
      generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      UNIQUE KEY unique_qr (username, email)
    )
  `);
  conn.release();
}

// Import students from CSV - run once on server start or via API
async function importStudentsFromCSV() {
  const students = [];
  return new Promise((resolve, reject) => {
    fs.createReadStream(path.join(__dirname, 'student_list_sample.csv'))
      .pipe(csv())
      .on('data', (row) => students.push(row))
      .on('end', async () => {
        console.log('CSV file parsed, inserting to DB...');
        try {
          const conn = await pool.getConnection();
          for (const student of students) {
            await conn.execute(
              `INSERT IGNORE INTO students (enrollment_no, name, classroom, class_name, division)
               VALUES (?, ?, ?, ?, ?)`,
              [
                student['Enrollment Number'],
                student['Student Name'],
                student['Classroom Number'],
                student['Class Name'],
                student['Division'],
              ]
            );
          }
          conn.release();
          console.log('Students inserted successfully');
          resolve();
        } catch (err) {
          console.error('Error inserting students:', err);
          reject(err);
        }
      });
  });
}

// Register API: allow students to self-register (Student ID, Full Name, Email, Branch, Classroom)
app.post('/api/register', async (req, res) => {
  const { username, fullname, email, branch, classroom } = req.body;
  if (!username || !fullname || !email)
    return res.status(400).json({ error: 'Username, full name and email are required' });

  try {
    const conn = await pool.getConnection();
    // Check for duplicate username or email
    const [existing] = await conn.query(
      'SELECT id FROM users WHERE username = ? OR email = ?',
      [username, email]
    );
    if (existing.length > 0) {
      conn.release();
      return res.status(409).json({ error: 'Username or Email already exists' });
    }
    await conn.query(
      'INSERT INTO users (username, fullname, email, branch, classroom) VALUES (?, ?, ?, ?, ?)',
      [username, fullname, email, branch || null, classroom || null]
    );
    conn.release();
    res.json({ message: 'User registered successfully' });
  } catch (err) {
    console.error('/api/register error:', err);
    res.status(500).json({ error: 'Server error' });
  }
});

// Login API: direct login with username + email
app.post('/api/login', async (req, res) => {
  const { username, email } = req.body;
  if (!username || !email) return res.status(400).json({ error: 'Missing Student ID or Email' });

  try {
    const [rows] = await pool.query('SELECT * FROM users WHERE username = ? AND email = ?', [username, email]);
    if (rows.length === 0) return res.status(401).json({ error: 'Invalid Student ID or Email' });

    const user = rows[0];
    const token = jwt.sign({ id: user.id, username: user.username }, JWT_SECRET, { expiresIn: '2h' });
    res.json({ token });
  } catch (err) {
    console.error('Login error:', err);
    res.status(500).json({ error: 'Server error' });
  }
});

// Auth middleware
function authMiddleware(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader) return res.status(401).json({ error: 'Missing authorization header' });

  const token = authHeader.split(' ')[1];
  if (!token) return res.status(401).json({ error: 'Missing token' });

  try {
    const payload = jwt.verify(token, JWT_SECRET);
    req.user = payload;
    next();
  } catch (err) {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }
}

// Get user profile (protected)
app.get('/api/user-profile', authMiddleware, async (req, res) => {
  try {
    const [rows] = await pool.query(
      'SELECT id, username, fullname, email, branch, classroom FROM users WHERE id = ?',
      [req.user.id]
    );
    if (rows.length === 0) return res.status(404).json({ error: 'User not found' });
    res.json({ user: rows[0] });
  } catch (err) {
    console.error('User profile error:', err);
    res.status(500).json({ error: 'Server error' });
  }
});

// QR Code generation and retrieval by teacher and students

// Teacher generates QR code for a student
app.post('/api/generate-qr', authMiddleware, async (req, res) => {
  // Should verify teacher role here if roles implemented
  const { username, email, qr_data } = req.body;
  if (!username || !email || !qr_data) return res.status(400).json({ error: 'Missing data' });

  try {
    const conn = await pool.getConnection();
    await conn.query(
      `INSERT INTO qr_codes (username, email, qr_data)
       VALUES (?, ?, ?)
       ON DUPLICATE KEY UPDATE qr_data = ?, generated_at = NOW()`,
      [username, email, qr_data, qr_data]
    );
    conn.release();
    res.json({ message: 'QR code generated successfully' });
  } catch (err) {
    console.error('Generate QR error:', err);
    res.status(500).json({ error: 'Server error' });
  }
});

// Student fetches own QR code
app.get('/api/my-qr', authMiddleware, async (req, res) => {
  try {
    const user = req.user;
    const [users] = await pool.query('SELECT email FROM users WHERE id = ?', [user.id]);
    if (users.length === 0) return res.status(404).json({ error: 'User not found' });
    const email = users[0].email.toLowerCase();

    const [rows] = await pool.query(
      'SELECT qr_data FROM qr_codes WHERE username = ? AND email = ?',
      [user.username, email]
    );
    if (rows.length === 0) return res.json({ qr_data: null });
    res.json({ qr_data: rows[0].qr_data });
  } catch (err) {
    console.error('Fetch QR error:', err);
    res.status(500).json({ error: 'Server error' });
  }
});

// Helper to get student by enrollment number
async function getStudentByEnrollment(enrollment_no) {
  const [rows] = await pool.query('SELECT * FROM students WHERE enrollment_no = ?', [enrollment_no]);
  return rows[0];
}

// API: Get all students
app.get('/students', async (req, res) => {
  try {
    const [rows] = await pool.query('SELECT * FROM students');
    res.json(rows);
  } catch (err) {
    res.status(500).json({ error: 'Database error' });
  }
});

// New API: Get username → email mapping for dashboard use
app.get('/api/user-emails', async (req, res) => {
  try {
    const [rows] = await pool.query('SELECT username, email FROM users');
    res.json(rows);
  } catch (err) {
    res.status(500).json({ error: 'Failed to fetch user emails' });
  }
});

// API: Mark attendance
app.post('/attendance/mark', async (req, res) => {
  const { enrollment_no, date, present } = req.body;
  if (!enrollment_no || !date) return res.status(400).json({ error: 'Missing enrollment_no or date' });

  try {
    const student = await getStudentByEnrollment(enrollment_no);
    if (!student) return res.status(404).json({ error: 'Student not found' });

    const [existing] = await pool.query(
      'SELECT * FROM attendance WHERE student_id = ? AND date = ?',
      [student.id, date]
    );

    if (existing.length > 0) {
      await pool.query(
        'UPDATE attendance SET present = ? WHERE id = ?',
        [present === undefined ? true : present, existing[0].id]
      );
    } else {
      await pool.query(
        'INSERT INTO attendance (student_id, date, present) VALUES (?, ?, ?)',
        [student.id, date, present === undefined ? true : present]
      );
    }
    res.json({ message: 'Attendance marked' });
  } catch (err) {
    res.status(500).json({ error: 'Database error' });
  }
});

// API: Get attendance for a student by enrollment number
app.get('/attendance/:enrollment_no', async (req, res) => {
  const enrollment_no = req.params.enrollment_no;
  try {
    const student = await getStudentByEnrollment(enrollment_no);
    if (!student) return res.status(404).json({ error: 'Student not found' });

    const [rows] = await pool.query(
      'SELECT date, present FROM attendance WHERE student_id = ? ORDER BY date DESC',
      [student.id]
    );
    res.json({ student, attendance: rows });
  } catch (err) {
    res.status(500).json({ error: 'Database error' });
  }
});

// Initialize server and database on start
(async () => {
  try {
    await createTables();
    await importStudentsFromCSV();
  } catch (e) {
    console.error('Setup error:', e);
  }
})();

// Serve default dashboard.html
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'dashboard.html'));
});

// Proxy device status from Python API server
app.get('/device-status', async (req, res) => {
  try {
    const response = await axios.get('http://localhost:8080/device-status');
    res.json(response.data);
  } catch (error) {
    console.error('Error fetching device status:', error.message);
    res.status(500).json({ error: 'Error fetching device status' });
  }
});

app.listen(port, () => {
  console.log(`Backend server listening at http://localhost:${port}`);
});
