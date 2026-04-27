// ═══════════════════════════════════════════
// FaceVoiceAuth — Jenkins Declarative Pipeline
// Full CI/CD with 12 stages from checkout to production
// ═══════════════════════════════════════════

pipeline {
    agent any

    environment {
        REGISTRY_URL  = credentials('REGISTRY_URL') ?: 'docker.io'
        DOCKER_CREDS  = credentials('docker-hub-credentials')
        IMAGE_TAG     = "${env.GIT_COMMIT?.take(8) ?: 'latest'}"
        BACKEND_IMAGE = "${REGISTRY_URL}/facevoiceauth-backend:${IMAGE_TAG}"
        FRONTEND_IMAGE = "${REGISTRY_URL}/facevoiceauth-frontend:${IMAGE_TAG}"
        SLACK_CHANNEL = '#deployments'
        STAGING_HOST  = credentials('staging-ssh-host')
        PROD_HOST     = credentials('prod-ssh-host')
    }

    options {
        timeout(time: 45, unit: 'MINUTES')
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    triggers {
        githubPush()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_COMMIT_SHORT = sh(returnStdout: true, script: 'git rev-parse --short HEAD').trim()
                    env.GIT_BRANCH_NAME = sh(returnStdout: true, script: 'git rev-parse --abbrev-ref HEAD').trim()
                }
                echo "Building commit: ${env.GIT_COMMIT_SHORT} on branch: ${env.GIT_BRANCH_NAME}"
            }
        }

        stage('Environment Setup') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install --upgrade pip
                    pip install -r backend/requirements.txt
                    python -c "import dlib; print(f'dlib version: {dlib.__version__}')" || echo "dlib not available in CI"
                '''
            }
        }

        stage('Lint & Format') {
            parallel {
                stage('Flake8') {
                    steps {
                        sh '''
                            . .venv/bin/activate
                            flake8 backend/ --max-line-length=120 --exclude=__pycache__,.venv --count
                        '''
                    }
                }
                stage('Black') {
                    steps {
                        sh '''
                            . .venv/bin/activate
                            black --check --line-length=120 backend/
                        '''
                    }
                }
                stage('isort') {
                    steps {
                        sh '''
                            . .venv/bin/activate
                            isort --check-only --profile black backend/
                        '''
                    }
                }
            }
        }

        stage('Unit Tests') {
            steps {
                sh '''
                    . .venv/bin/activate
                    pytest backend/tests/ \
                        --cov=backend \
                        --cov-report=xml:coverage.xml \
                        --cov-report=html:htmlcov \
                        --junitxml=test-results.xml \
                        -v --tb=short
                '''
            }
            post {
                always {
                    junit 'test-results.xml'
                    publishHTML(target: [
                        reportDir: 'htmlcov',
                        reportFiles: 'index.html',
                        reportName: 'Coverage Report'
                    ])
                }
            }
        }

        stage('Security Scan') {
            parallel {
                stage('Bandit') {
                    steps {
                        sh '''
                            . .venv/bin/activate
                            bandit -r backend/ -ll -ii --format json -o bandit-report.json || true
                        '''
                    }
                }
                stage('Safety') {
                    steps {
                        sh '''
                            . .venv/bin/activate
                            safety check -r backend/requirements.txt --output json > safety-report.json || true
                        '''
                    }
                }
            }
        }

        stage('Docker Build') {
            steps {
                sh """
                    docker build -f docker/Dockerfile.backend -t ${BACKEND_IMAGE} .
                    docker build -f docker/Dockerfile.frontend -t ${FRONTEND_IMAGE} .
                    docker tag ${BACKEND_IMAGE} ${REGISTRY_URL}/facevoiceauth-backend:latest
                    docker tag ${FRONTEND_IMAGE} ${REGISTRY_URL}/facevoiceauth-frontend:latest
                """
            }
        }

        stage('Integration Tests') {
            steps {
                sh '''
                    docker-compose -f docker-compose.yml up -d
                    sleep 30
                    curl -sf http://localhost:8000/health || (docker-compose logs backend && exit 1)
                    curl -sf http://localhost/ || (docker-compose logs frontend && exit 1)
                    docker-compose down -v
                '''
            }
        }

        stage('Push to Registry') {
            when {
                branch 'main'
            }
            steps {
                sh """
                    echo ${DOCKER_CREDS_PSW} | docker login ${REGISTRY_URL} -u ${DOCKER_CREDS_USR} --password-stdin
                    docker push ${BACKEND_IMAGE}
                    docker push ${FRONTEND_IMAGE}
                    docker push ${REGISTRY_URL}/facevoiceauth-backend:latest
                    docker push ${REGISTRY_URL}/facevoiceauth-frontend:latest
                """
            }
        }

        stage('Deploy to Staging') {
            when {
                branch 'main'
            }
            steps {
                sshagent(['staging-ssh-key']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no deploy@${STAGING_HOST} '
                            cd /opt/facevoiceauth &&
                            docker pull ${BACKEND_IMAGE} &&
                            docker pull ${FRONTEND_IMAGE} &&
                            docker-compose -f docker-compose.prod.yml up -d
                        '
                    """
                }
            }
        }

        stage('Smoke Test Staging') {
            when {
                branch 'main'
            }
            steps {
                sh """
                    sleep 15
                    STATUS=\$(curl -sf -o /dev/null -w '%{http_code}' http://${STAGING_HOST}/health)
                    if [ "\$STATUS" != "200" ]; then
                        echo "Smoke test failed: HTTP \$STATUS"
                        exit 1
                    fi
                    echo "Staging smoke test passed: HTTP \$STATUS"
                """
            }
        }

        stage('Deploy to Production') {
            when {
                branch 'main'
            }
            steps {
                input message: 'Deploy to Production?', ok: 'Deploy', submitter: 'admin'
                sshagent(['prod-ssh-key']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no deploy@${PROD_HOST} '
                            cd /opt/facevoiceauth &&
                            docker pull ${BACKEND_IMAGE} &&
                            docker pull ${FRONTEND_IMAGE} &&
                            docker-compose -f docker-compose.prod.yml up -d &&
                            sleep 10 &&
                            curl -sf http://localhost/health || exit 1
                        '
                    """
                }
            }
        }
    }

    post {
        always {
            script {
                def buildStatus = currentBuild.result ?: 'SUCCESS'
                def color = buildStatus == 'SUCCESS' ? 'good' : 'danger'
                def emoji = buildStatus == 'SUCCESS' ? '✅' : '❌'

                echo "${emoji} Build ${buildStatus}: ${env.JOB_NAME} #${env.BUILD_NUMBER}"
            }
            cleanWs()
        }
        success {
            echo '✅ Pipeline completed successfully'
        }
        failure {
            echo '❌ Pipeline failed'
        }
    }
}
