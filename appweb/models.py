from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator


class AssessmentResult(models.Model):
    # Cada diagnóstico pertence a um usuário. Registros antigos (anteriores
    # ao login) ficam sem dono e não aparecem para ninguém.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='diagnosticos_esg',
        null=True,
        blank=True,
    )
    environmental_score = models.IntegerField(default=0)
    social_score = models.IntegerField(default=0)
    governance_score = models.IntegerField(default=0)
    overall_score = models.IntegerField(default=0)
    weakest_pillar = models.CharField(max_length=50, default='Ambiental')
    created_at = models.DateTimeField(auto_now_add=True)

    def calculate_scores(self):
        scores = {
            'Ambiental': self.environmental_score,
            'Social': self.social_score,
            'Governança': self.governance_score,
        }
        self.overall_score = self.environmental_score + self.social_score + self.governance_score
        self.weakest_pillar = min(scores, key=scores.get)
        return self

    def add_points(self, pillar):
        if (str(pillar).lower() == 'social'):
            self.social_score += 1
        elif (str(pillar).lower() == 'ambiental'):
            self.environmental_score += 1
        elif (str(pillar).lower() == 'governança'):
            self.governance_score += 1
        else:
            print('Incorrect pillar!')

    def __str__(self):
        return f"Resultado ESG {self.overall_score}"


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.email}"

class ESGPillar(models.Model):
    topic = models.CharField(max_length=120)
    question = models.CharField(max_length=500)
    pillar = models.CharField(
        max_length= 15,
        choices= [
            ('Ambiental', 'ambiental'),
            ('Social', 'social'),
            ('Governança', 'governança')
        ]
    )

    def __str__(self):
        return f"[{self.topic} - {self.pillar}]:   {self.question}"

class RegistroResiduo(models.Model):
    DESTINOS = [
        ('reciclado', 'Reciclado'),
        ('nao_reciclado', 'Não reciclado'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='registros_residuos',
        null=True,
        blank=True,
    )
    data = models.DateField()
    local = models.CharField(max_length=100)

    quantidade_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    destino = models.CharField(
        max_length=20,
        choices=DESTINOS,  
    )

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Registro de resíduo'
        verbose_name_plural = 'Registros de resíduos'

    def __str__(self):
        return (
            f"{self.local} - {self.quantidade_kg} kg "
            f"- {self.get_destino_display()}"
        )


class ItemConcluido(models.Model):
    """Quiz ou desafio do microlearning concluído por um usuário.

    É a fonte da progressão individual (pontos, nível e impacto): cada usuário
    só enxerga e altera os próprios itens.
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='itens_concluidos',
    )
    item_id = models.CharField(max_length=50)
    concluido_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['concluido_em', 'id']
        verbose_name = 'Item concluído'
        verbose_name_plural = 'Itens concluídos'
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'item_id'],
                name='item_concluido_unico_por_usuario',
            ),
        ]

    def __str__(self):
        return f"{self.usuario} - {self.item_id}"
