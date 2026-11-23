from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import ContactMessage


class ContactMessageForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'message']
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'Seu nome',
                'class': 'field-input',
            }),
            'email': forms.EmailInput(attrs={
                'placeholder': 'seu@email.com',
                'class': 'field-input',
            }),
            'message': forms.Textarea(attrs={
                'placeholder': 'Escreva sua mensagem...',
                'class': 'field-input field-textarea',
                'rows': 5,
            }),
        }


class EntrarForm(AuthenticationForm):
    error_messages = {
        'invalid_login': 'Usuário ou senha incorretos.',
        'inactive': 'Esta conta está desativada.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Usuário'
        self.fields['password'].label = 'Senha'
        self.fields['username'].widget.attrs.update({
            'class': 'campo',
            'autocomplete': 'username',
        })
        self.fields['password'].widget.attrs.update({
            'class': 'campo',
            'autocomplete': 'current-password',
        })


class CadastroForm(UserCreationForm):
    email = forms.EmailField(
        label='E-mail',
        required=True,
        widget=forms.EmailInput(attrs={'class': 'campo', 'autocomplete': 'email'}),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Usuário'
        self.fields['username'].help_text = (
            'Até 150 caracteres: letras, números e @/./+/-/_.'
        )
        self.fields['username'].widget.attrs.update({
            'class': 'campo',
            'autocomplete': 'username',
        })
        for nome in ('password1', 'password2'):
            self.fields[nome].widget.attrs.update({
                'class': 'campo',
                'autocomplete': 'new-password',
            })

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        modelo = get_user_model()

        if modelo.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Já existe uma conta com este e-mail.')

        return email
