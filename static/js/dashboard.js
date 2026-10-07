window.getRecommendations = function() {
    const requiredFields = ['course', 'year', 'cgpa', 'income', 'category', 'state'];

    for (let field of requiredFields) {
        if (!document.getElementById(field).value) {
            alert('⚠️ Please complete your profile first!');
            return;
        }
    }

    alert('🎯 Analyzing your profile...');

    const profileData = {
        fullname: document.getElementById('fullname').value,
        course: document.getElementById('course').value,
        year: document.getElementById('year').value,
        cgpa: document.getElementById('cgpa').value,
        income: document.getElementById('income').value,
        category: document.getElementById('category').value,
        state: document.getElementById('state').value,
        skills: document.getElementById('skills').value
    };

    fetch('/get-recommendations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(profileData)
        })
        .then(res => res.json())
        .then(data => {
            alert('🎓 Found ' + data.length + ' matching scholarships!');
            console.log(data);
        })
        .catch(err => {
            console.error(err);
            alert('❌ Error fetching recommendations');
        });
};