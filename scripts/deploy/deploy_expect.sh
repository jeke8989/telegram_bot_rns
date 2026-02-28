#!/usr/bin/expect -f

set timeout 60
set password [exec grep "^SERVER_PASSWORD=" ../../.env | cut -d= -f2-]
set server [exec sh -c {grep "^SERVER_USER=" ../../.env | cut -d= -f2}]@[exec sh -c {grep "^SERVER_HOST=" ../../.env | cut -d= -f2}]

# Copy database.py
spawn scp -o StrictHostKeyChecking=no app/database.py $server:/var/www/nc-miniapp/app/
expect {
    "password:" { send "$password\r"; expect eof }
    timeout { puts "Timeout copying database.py"; exit 1 }
}

# Copy server.py
spawn scp -o StrictHostKeyChecking=no mini_app/server.py $server:/var/www/nc-miniapp/mini_app/
expect {
    "password:" { send "$password\r"; expect eof }
    timeout { puts "Timeout copying server.py"; exit 1 }
}

# Copy meeting.html
spawn scp -o StrictHostKeyChecking=no mini_app/static/meeting.html $server:/var/www/nc-miniapp/mini_app/static/
expect {
    "password:" { send "$password\r"; expect eof }
    timeout { puts "Timeout copying meeting.html"; exit 1 }
}

# Restart services
spawn ssh -o StrictHostKeyChecking=no $server "cd /var/www/nc-miniapp && docker compose restart bot webapp && docker ps"
expect {
    "password:" { send "$password\r"; expect eof }
    timeout { puts "Timeout restarting services"; exit 1 }
}

puts "\nDeployment complete!"
